#!/usr/bin/env python3
"""Guard active_outputs ownership when the old direct stream closes."""
import hashlib
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'out/hal-dtshd-truehd-buffer8-latency16.so'
TARGET = ROOT / 'out/hal-direct-owner-guard.so'
ASM = ROOT / 'round3-analysis/direct_owner_guard.S'
SOURCE_SHA = '5e6d576553063e4610ccc52bada7aa81a9b79e171d2ed32ad97fb430acb3b6b7'
SITE_VA = 0x3c762
HOOK_VA = 0x6dd80
DELTA = 0x1000


def thumb_b(src, dst):
    delta = dst - (src + 4)
    assert delta % 2 == 0 and -(1 << 24) <= delta < (1 << 24)
    bits = delta & ((1 << 25) - 1)
    s = (bits >> 24) & 1
    i1, i2 = (bits >> 23) & 1, (bits >> 22) & 1
    j1, j2 = (~(i1 ^ s)) & 1, (~(i2 ^ s)) & 1
    return struct.pack('<HH',
                       0xf000 | (s << 10) | ((bits >> 12) & 0x3ff),
                       0x9000 | (j1 << 13) | (j2 << 11) | ((bits >> 1) & 0x7ff))


blob = bytearray(SOURCE.read_bytes())
assert hashlib.sha256(blob).hexdigest() == SOURCE_SHA
assert blob[SITE_VA - DELTA:SITE_VA - DELTA + 4] == bytes.fromhex('05eb8000')
with tempfile.TemporaryDirectory(prefix='direct-owner-guard-') as tmpdir:
    tmp = Path(tmpdir)
    obj, elf, raw = tmp / 'hook.o', tmp / 'hook.elf', tmp / 'hook.bin'
    subprocess.run(['arm-linux-gnueabihf-as', '-mthumb', '-march=armv7-a',
                    '-o', str(obj), str(ASM)], check=True)
    subprocess.run(['arm-linux-gnueabihf-ld', '-m', 'armelf_linux_eabi',
                    f'-Ttext={HOOK_VA:#x}', '-o', str(elf), str(obj)],
                   check=True, capture_output=True)
    rel = subprocess.check_output(['arm-linux-gnueabihf-readelf', '-r', str(elf)],
                                  text=True)
    assert 'There are no relocations' in rel
    subprocess.run(['arm-linux-gnueabihf-objcopy', '-O', 'binary',
                    '--only-section=.text', str(elf), str(raw)], check=True)
    hook = raw.read_bytes()
assert len(hook) <= 0x40
assert not any(blob[HOOK_VA - DELTA:HOOK_VA - DELTA + len(hook)])
blob[HOOK_VA - DELTA:HOOK_VA - DELTA + len(hook)] = hook
blob[SITE_VA - DELTA:SITE_VA - DELTA + 4] = thumb_b(SITE_VA, HOOK_VA)
TARGET.write_bytes(blob)
print(TARGET, hashlib.sha256(blob).hexdigest(), 'hook bytes', len(hook))
