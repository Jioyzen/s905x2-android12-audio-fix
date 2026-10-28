#!/usr/bin/env python3
"""Build a TrueHD-only 8-period ALSA queue candidate, without deploying it."""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path('/home/zeng/s905x2/work')
SOURCE = ROOT / 'out/hal-dts8v8-posdiv16-returnfix-truehd192.so'
TARGET = ROOT / 'out/hal-dts8v8-posdiv16-truehd192-buffer8.so'
ASM = ROOT / 'round3-analysis/hal_truehd_buffer_cave.S'
BASE_SHA = 'fa3efdac392b8f4cec0f2e640ef1c40366e73501a2689cbaf85399d2cbec9d67'
CAVE_VA = 0x6d9c0
RETURN_VA = 0x5b808
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
assert original[0x5a804:0x5a808] == bytes.fromhex('12f0dcb8')
object_file = Path('/tmp/hal_truehd_buffer_cave.o')
elf_file = Path('/tmp/hal_truehd_buffer_cave.elf')
binary_file = Path('/tmp/hal_truehd_buffer_cave.bin')
subprocess.run(['arm-linux-gnueabihf-as', '-march=armv7-a', '-o', str(object_file), str(ASM)], check=True)
subprocess.run(['arm-linux-gnueabihf-ld', '-Ttext=0x6d9c0', '-o', str(elf_file), str(object_file)], check=True)
subprocess.run(['arm-linux-gnueabihf-objcopy', '-O', 'binary', '--only-section=.text',
                str(elf_file), str(binary_file)], check=True)
cave = binary_file.read_bytes()
jump_va = CAVE_VA + len(cave)
assert jump_va % 2 == 0 and jump_va + 4 < 0x6da00
cave += branch_w(jump_va, RETURN_VA)
offset = CAVE_VA - TEXT_DELTA
assert all(byte == 0 for byte in original[0x6c9e0:offset + len(cave)])
patched = bytearray(original)
patched[offset:offset + len(cave)] = cave
TARGET.write_bytes(patched)
print(TARGET)
print(hashlib.sha256(patched).hexdigest())
