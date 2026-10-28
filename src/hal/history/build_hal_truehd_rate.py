#!/usr/bin/env python3
"""Add the TrueHD 192 kHz carrier to the tested non-MS12 DTS-HD HAL."""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path('/home/zeng/s905x2/work')
SOURCE = ROOT / 'out/hal-dts8v8-posdiv16-returnfix.so'
TARGET = ROOT / 'out/hal-dts8v8-posdiv16-returnfix-truehd192.so'
ASM = ROOT / 'round3-analysis/hal_truehd_rate_cave.S'
BASE_SHA = 'b487d5fdecca8b6f07f9e606db1fc1c9386ed091dd6844d94cb9b3eef9050e84'
CAVE_VA = 0x6d9c0
JUMP_VA = 0x6d9dc
RETURN_VA = 0x5b808
TEXT_FILE_OFFSET_DELTA = 0x1000


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
assert original[0x5a804:0x5a808] == bytes.fromhex('12f0dcb8')
assert original[0x6c9c0:0x6c9da] == bytes.fromhex(
    '032906d108214ef60063c0f20203c2f8fc302de9f043edf717bf')
assert branch_w(0x6d9d6, RETURN_VA) == bytes.fromhex('edf717bf')
object_file = Path('/tmp/hal_truehd_rate_cave.o')
elf_file = Path('/tmp/hal_truehd_rate_cave.elf')
binary_file = Path('/tmp/hal_truehd_rate_cave.bin')
subprocess.run(['arm-linux-gnueabihf-as', '-march=armv7-a', '-o', str(object_file), str(ASM)], check=True)
subprocess.run(['arm-linux-gnueabihf-ld', '-Ttext=0x6d9c0', '-o', str(elf_file), str(object_file)], check=True)
subprocess.run(['arm-linux-gnueabihf-objcopy', '-O', 'binary', '--only-section=.text',
                str(elf_file), str(binary_file)], check=True)
cave = binary_file.read_bytes()
assert len(cave) == JUMP_VA - CAVE_VA
cave += branch_w(JUMP_VA, RETURN_VA)
assert len(cave) == 32 and CAVE_VA + len(cave) <= 0x6e000
patched = bytearray(original)
offset = CAVE_VA - TEXT_FILE_OFFSET_DELTA
patched[offset:offset + len(cave)] = cave
assert all(a == b or offset <= i < offset + len(cave)
           for i, (a, b) in enumerate(zip(original, patched)))
TARGET.write_bytes(patched)
print(TARGET)
print(hashlib.sha256(patched).hexdigest())
