#!/usr/bin/env python3
"""Add a standard TrueHD role fallback after the unchanged vendor role table.
Reuse only the old no-role diagnostic and its literals. Legacy MIME still works.
"""
from pathlib import Path
import struct, subprocess, sys, hashlib
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
D=Path(__file__).resolve().parent
vndk = len(sys.argv) > 1 and sys.argv[1] == 'vndk'
suffix = '-vndk' if vndk else ''
b=bytearray((D/('libstagefright_xmlparser'+suffix+'-original.so')).read_bytes())
assert hashlib.sha256(b).hexdigest() == ('cc44c1808c3a48b9ac6c5e8ff1756a963aefbd474fa401962ea7facedf360ab4' if vndk else '12d7ec813c900ac8d1921438e86f128ee330362e882ec0cb5b109f9595a84c68')
start=0xf2aa if vndk else 0xfcba
base=start&~3; lead=start-base
std_pool=0xf590 if vndk else 0xffa4
role_pool=std_pool-4
compare=0x131e0 if vndk else 0x11780
fmt_addr=struct.unpack_from('<i',b,std_pool-0x1000)[0]+start+16
assert b[fmt_addr:fmt_addr+len(b'AmAVUtils::have no Component role')] == b'AmAVUtils::have no Component role'
role_addr=b.index(b'audio_decoder.truehd\0')
asm=f'''.syntax unified
.thumb
.text
.global mime_alias
.type mime_alias,%function
.org {lead}
mime_alias:
mov r0,r5
ldr r1,std_literal
add r1,pc
blx compare
cbnz r0,done
ldr r0,role_literal
add r0,pc
.short 0xe000
done:
.org {role_pool-base}
role_literal: .word {role_addr-(start+14+4)}
.org {std_pool-base}
std_literal: .word {fmt_addr-(start+4+4)}
.global compare
.type compare,%function
'''
src=D/'xml_mime_alias.S';obj=D/'xml_mime_alias.o';elf=D/'xml_mime_alias.elf';src.write_text(asm)
clang='/home/zeng/Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin/armv7a-linux-androideabi26-clang'
subprocess.run([clang,'-c',str(src),'-o',str(obj)],check=True)
subprocess.run([clang,'-nostdlib','-no-pie','-Wl,--defsym=compare='+hex(compare),'-Wl,-Ttext='+hex(base),'-Wl,-e,mime_alias',str(obj),'-o',str(elf)],check=True)
with elf.open('rb') as f:code=ELFFile(f).get_section_by_name('.text').data()
ins=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(code[lead:lead+18],start))
assert sum(i.size for i in ins)==18
assert ins[3].mnemonic=='blx' and ins[3].op_str=='#'+hex(compare)
assert ins[-1].mnemonic=='b' and ins[-1].op_str=='#'+hex(start+20)
b[start-0x1000:start-0x1000+18]=code[lead:lead+18]
for p in [role_pool,std_pool]:b[p-0x1000:p-0x1000+4]=code[p-base:p-base+4]
b[fmt_addr:fmt_addr+len(b'audio/true-hd\0')]=b'audio/true-hd\0'
# Keep the standard encoder role correct too; reuse the removed matched-role
# diagnostic while preserving the existing table return for every legacy MIME.
def branch(at, dest, condition=None):
    diff=dest-at-4; assert diff % 2 == 0
    if condition is None:
        assert -2048 <= diff <= 2046
        return 0xe000 | ((diff//2)&0x7ff)
    assert -256 <= diff <= 254
    return 0xd000 | (condition<<8) | ((diff//2)&0xff)
def write_half(at, op):struct.pack_into('<H', b, at-0x1000, op)
match=0xf2c4 if vndk else 0xfcd4
helper=match+4 if vndk else match+2
resume=0xf2d4 if vndk else 0xfce2
ret=start+20
encoder_pool=0xf598 if vndk else 0xffac
encoder_addr=b.index(b'audio_encoder.truehd\0')
write_half(start+16, branch(start+16, helper))
if vndk:
    write_half(match, 0x2504) # original table needs r5=4 (decoder role offset)
    write_half(match+2, branch(match+2,resume))
else:write_half(match,branch(match,resume))
write_half(helper,0x2c00) # cmp r4,#0
write_half(helper+2,branch(helper+2,ret,0))
disp=encoder_pool-((helper+4+4)&~3); assert 0<=disp<=1020 and disp%4==0
write_half(helper+4,0x4800 | (disp//4))
write_half(helper+6,0x4478) # add r0,pc
write_half(helper+8,branch(helper+8,ret))
write_half(helper+10,0xbf00)
struct.pack_into('<i',b,encoder_pool-0x1000,encoder_addr-(helper+10))
out=D/('libstagefright_xmlparser'+suffix+'-truehd-mime.so');out.write_bytes(b)
for i in Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(bytes(b[start-0x1000:start-0x1000+18]),start):print(hex(i.address),i.mnemonic,i.op_str)
print('string',hex(fmt_addr),'role',hex(role_addr),out)
