#!/usr/bin/env python3
"""Add only explicit DTS_HD's carrier rate to the persisted, tested HAL."""
from pathlib import Path
import hashlib
import struct
import subprocess
import tempfile
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'out/hal-ac3-n1-dtses-core.so'
TARGET = ROOT / 'out/hal-exoplayer-native-dtshd192.so'
CAVE = 0x6db70
HOOK = 0x6db50
DELTA = 0x1000

def branch(src, dst):
    d = dst-src-4
    assert d % 2 == 0 and -(1<<24) <= d < (1<<24)
    s=(d>>24)&1; i1=(d>>23)&1; i2=(d>>22)&1
    j1=(~i1^s)&1; j2=(~i2^s)&1
    return struct.pack('<HH', 0xf000|(s<<10)|((d>>12)&0x3ff),
                       0x9000|(j1<<13)|(j2<<11)|((d>>1)&0x7ff))

original = SOURCE.read_bytes()
assert hashlib.sha256(original).hexdigest() == '6c0eb48c390b4903f7aafceea6a0dd2dcd7cca84bc9a73e993412149b504332b'
assert original[HOOK-DELTA:HOOK-DELTA+4] == branch(HOOK,0x6d9c0)
assert not any(original[CAVE-DELTA:0x6dc00-DELTA])
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp); obj=p/'hook.o'; elf=p/'hook.elf'; binary=p/'hook.bin'
    asm=Path(__file__).with_name('exoplayer_native_dtshd_rate.S')
    subprocess.run(['arm-linux-gnueabihf-as','-mthumb','-march=armv7-a','-o',str(obj),str(asm)],check=True)
    subprocess.run(['arm-linux-gnueabihf-ld',f'-Ttext={CAVE:#x}','-o',str(elf),str(obj)],check=True,capture_output=True)
    assert 'There are no relocations' in subprocess.check_output(['arm-linux-gnueabihf-readelf','-r',str(elf)],text=True)
    subprocess.run(['arm-linux-gnueabihf-objcopy','-O','binary','-j','.text',str(elf),str(binary)],check=True)
    code=binary.read_bytes()
assert CAVE % 2 == 0 and CAVE+len(code) <= 0x6dc00
patched=bytearray(original)
patched[CAVE-DELTA:CAVE-DELTA+len(code)]=code
patched[HOOK-DELTA:HOOK-DELTA+4]=branch(HOOK,CAVE)
assert all(a==b or CAVE-DELTA <= i < CAVE-DELTA+len(code) or HOOK-DELTA <= i < HOOK-DELTA+4
           for i,(a,b) in enumerate(zip(original,patched)))
TARGET.write_bytes(patched)
for insn in Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(code,CAVE):
    print(f'{insn.address:#x}: {insn.bytes.hex()} {insn.mnemonic} {insn.op_str}')
print(TARGET, len(code), hashlib.sha256(patched).hexdigest())
