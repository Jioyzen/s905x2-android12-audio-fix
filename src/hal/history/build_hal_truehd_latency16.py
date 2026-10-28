#!/usr/bin/env python3
"""Build a TrueHD-only corrected latency reporting candidate."""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path('/home/zeng/s905x2/work')
SOURCE = ROOT / 'out/hal-dts8v8-posdiv16-truehd192-buffer8.so'
TARGET = ROOT / 'out/hal-dtshd-truehd-buffer8-latency16.so'
ASM = ROOT / 'round3-analysis/hal_truehd_latency16_cave.S'
BASE_SHA = 'cd4324662188ebedea0ae4faa3b5f0e7f4141994aebd1c90dbf7e2aacc601b82'
CAVE_VA = 0x6dab0
TEXT_DELTA = 0x1000


def branch_w(src, dst):
    delta = dst - (src + 4)
    assert delta % 2 == 0 and -(1 << 24) <= delta < (1 << 24)
    s = (delta >> 24) & 1
    i1 = (delta >> 23) & 1
    i2 = (delta >> 22) & 1
    j1 = (~i1 ^ s) & 1
    j2 = (~i2 ^ s) & 1
    first = 0xf000 | (s << 10) | ((delta >> 12) & 0x3ff)
    second = 0x9000 | (j1 << 13) | (j2 << 11) | ((delta >> 1) & 0x7ff)
    return first.to_bytes(2, 'little') + second.to_bytes(2, 'little')


original = SOURCE.read_bytes()
assert hashlib.sha256(original).hexdigest() == BASE_SHA
assert original[0x47194:0x47198] == bytes.fromhex('b0f1606f')
assert original[CAVE_VA - TEXT_DELTA:CAVE_VA - TEXT_DELTA + 16] == bytes(16)
obj = Path('/tmp/hal_truehd_latency16_cave.o')
elf = Path('/tmp/hal_truehd_latency16_cave.elf')
binfile = Path('/tmp/hal_truehd_latency16_cave.bin')
subprocess.run(['arm-linux-gnueabihf-as', '-march=armv7-a', '-o', str(obj), str(ASM)], check=True)
subprocess.run(['arm-linux-gnueabihf-ld', '-Ttext=0x6dab0', '-o', str(elf), str(obj)], check=True)
subprocess.run(['arm-linux-gnueabihf-objcopy', '-O', 'binary', '--only-section=.text',
                str(elf), str(binfile)], check=True)
cave = bytearray(binfile.read_bytes())
assert len(cave) == 16
assert cave[8:16] == bytes.fromhex('00bf00bf00bf00bf')
cave[8:12] = branch_w(0x6dab8, 0x481a6)
cave[12:16] = branch_w(0x6dabc, 0x4819a)
patched = bytearray(original)
patched[0x47194:0x47198] = branch_w(0x48194, CAVE_VA)
patched[CAVE_VA - TEXT_DELTA:CAVE_VA - TEXT_DELTA + 16] = cave
TARGET.write_bytes(patched)
print(TARGET)
print(hashlib.sha256(patched).hexdigest())
