#!/usr/bin/env python3
"""Accept standard audio/true-hd while retaining all existing vendor MIME paths.
Reuse only the two removed entry log calls and their private literals, with no
new executable mappings and no overwritten adjacent strings.
"""
from pathlib import Path
import struct, subprocess, hashlib
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
D = Path(__file__).resolve().parent
original = D / 'libmediavendor_ext-original.so'
original_data = original.read_bytes()
assert hashlib.sha256(original_data).hexdigest() == '156d4d2ae3dc528de660861953c9472eeccc88d6be9b3698a1f9f2c7b2892c51'
b = bytearray(original_data)
assert b[0x2ce4:0x2ce4+len(b'AmAVUtils::getComponentRole isEncoder :%d mime:%s \n\0')] == b'AmAVUtils::getComponentRole isEncoder :%d mime:%s \n\0'
assert b[0x34f7:0x3504] == b'audio/truehd\0'
clang = '/home/zeng/Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin/armv7a-linux-androideabi26-clang'
# getComponentRole and AGetComponentRole have the same MIME register r5.
for start, old_pool, std_pool in [(0x4812, 0x4b28, 0x4b2c), (0x6834, 0x6b8c, 0x6b90)]:
    base = start & ~3
    lead = start - base
    asm = f'''.syntax unified
.thumb
.text
.global mime_alias
.type mime_alias,%function
.org {lead}
mime_alias:
mov r0, r5
ldr r1, std_literal
add r1, pc
blx compare
cbnz r0, done
ldr r5, old_literal
add r5, pc
done:
.org {old_pool-base}
old_literal: .word {0x34f7-(start+14+4)}
.org {std_pool-base}
std_literal: .word {0x2ce4-(start+4+4)}
.global compare
.type compare,%function
'''
    src = D / 'mime_alias.S'; obj = D / 'mime_alias.o'; elf = D / 'mime_alias.elf'
    src.write_text(asm)
    subprocess.run([clang, '-c', str(src), '-o', str(obj)], check=True)
    subprocess.run([clang, '-nostdlib', '-no-pie', '-Wl,--defsym=compare=0x7180', '-Wl,-Ttext='+hex(base), '-Wl,-e,mime_alias', str(obj), '-o', str(elf)], check=True)
    with elf.open('rb') as f: code = ELFFile(f).get_section_by_name('.text').data()
    ins = list(Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(code[lead:lead+16], start))
    assert sum(i.size for i in ins)==16
    assert ins[3].mnemonic=='blx' and ins[3].op_str=='#0x7180'
    b[start-0x1000:start-0x1000+16] = code[lead:lead+16]
    for p in [old_pool,std_pool]: b[p-0x1000:p-0x1000+4] = code[p-base:p-base+4]
    for i in ins: print(hex(i.address), i.mnemonic, i.op_str)
# This format string was used only by the two entry logs removed above.
new = b'audio/true-hd\0'
b[0x2ce4:0x2ce4+len(new)] = new
out = D / 'libmediavendor_ext-truehd-mime.so'; out.write_bytes(b)
print(out)
# The vendor ACodec extension implements only DTS-HD and generic FFmpeg
# input-format queries. Add TrueHD through its equivalent compressed port
# structure, with its own index (0x7f100004) and standard MIME.
def asm_patch(start, size, body, symbols=None):
    base=start&~3; lead=start-base
    src=D/'truehd_coding.S'; obj=D/'truehd_coding.o'; elf=D/'truehd_coding.elf'
    src.write_text('.syntax unified\n.thumb\n.text\n.global patch\n.type patch,%function\n.org '+str(lead)+'\npatch:\n'+body+'\n')
    subprocess.run([clang,'-c',str(src),'-o',str(obj)],check=True)
    args=[clang,'-nostdlib','-no-pie','-Wl,-Ttext='+hex(base),'-Wl,-e,patch']
    for name,value in (symbols or {}).items(): args+=['-Wl,--defsym='+name+'='+hex(value)]
    subprocess.run(args+[str(obj),'-o',str(elf)],check=True)
    with elf.open('rb') as f:c=ELFFile(f).get_section_by_name('.text').data()[lead:lead+size]
    assert len(c)==size
    with elf.open('rb') as f: assert len(ELFFile(f).get_section_by_name('.text').data()) == lead+size
    b[start-0x1000:start-0x1000+size]=c
    for i in Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(c,start):print(hex(i.address),i.mnemonic,i.op_str)
def branch(at, dest, condition=None):
    diff = dest - at - 4
    assert diff % 2 == 0
    if condition is None:
        assert -2048 <= diff <= 2046
        op = 0xe000 | ((diff // 2) & 0x7ff)
    else:
        assert -256 <= diff <= 254
        op = 0xd000 | (condition << 8) | ((diff // 2) & 0xff)
    return '.short '+hex(op)
asm_patch(0x4e4c,16,'movs r0,#2\nmovt r0,#0x7f00\ncmp r4,r0\nbne.n other\nmovs r0,#1\npop {r4,pc}\nnop\nother:')
asm_patch(0x4e98,14,branch(0x4e98,0x4ea6)+'\nuxtb r1,r6\nlsls r1,r1,#1\nmovt r1,#0x7f10\n'+branch(0x4ea2,0x4faa)+'\nnop')
asm_patch(0x4ea8,6,'lsls r0,r6,#31\n'+branch(0x4eaa,0x4f5c,0)+'\nnop')
asm_patch(0x4fa4,6,branch(0x4fa4,0x4e9a)+'\nnop\nnop')
asm_patch(0x4fae,2,'.short 0xb100')
asm_patch(0x4fb0,18,branch(0x4fb0,0x5004)+'\nuxtb r0,r6\ncmp r0,#2\n'+branch(0x4fb6,0x4fc8,1)+'\nldr r2,[pc,#0x8c]\nadd r2,pc\nmov.w r3,#-1\n'+branch(0x4fc0,0x4fd4))
struct.pack_into('<i',b,0x5048-0x1000,0x2ce4-0x4fbe)
out=D/'libmediavendor_ext-truehd-mime.so';out.write_bytes(b)
