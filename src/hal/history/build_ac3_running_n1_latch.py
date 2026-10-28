#!/usr/bin/env python3
"""Re-latch existing HDMI N1 once after AC3 ALSA state becomes RUNNING."""
import hashlib
import struct
import subprocess
import tempfile
from pathlib import Path

from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'out/hal-truehd-post-first-burst.so'
TARGET = ROOT / 'out/hal-ac3-running-n1-latch.so'
ASM = ROOT / 'round3-analysis/ac3_running_n1_latch.S'
SOURCE_SHA = '89c73b0e069629347cc8d98eb276327acc9c444c54adcda392523cfeaa241e11'
SITE_VA = 0x3b776
HOOK_VA = 0x6dd90
DELTA = 0x1000


def thumb_bl(src, dst):
    delta = dst - (src + 4)
    assert delta % 2 == 0 and -(1 << 24) <= delta < (1 << 24)
    bits = delta & ((1 << 25) - 1)
    s = (bits >> 24) & 1
    i1, i2 = (bits >> 23) & 1, (bits >> 22) & 1
    j1, j2 = (~(i1 ^ s)) & 1, (~(i2 ^ s)) & 1
    return struct.pack('<HH',
                       0xf000 | (s << 10) | ((bits >> 12) & 0x3ff),
                       0xd000 | (j1 << 13) | (j2 << 11) | ((bits >> 1) & 0x7ff))


def verify_plt_targets(path):
    expected = {0x6cc90: 'pcm_get_htimestamp', 0x6bff0: 'open', 0x6bfc0: 'read', 0x6bfe0: 'close',
                0x6aef0: 'strstr', 0x6b050: 'strtoul',
                0x6c030: 'write'}
    with path.open('rb') as f:
        elf = ELFFile(f)
        rel = elf.get_section_by_name('.rel.plt')
        symtab = elf.get_section(rel['sh_link'])
        targets = {item['r_offset']: symtab.get_symbol(item['r_info_sym']).name
                   for item in rel.iter_relocations()}
    def immediate(word):
        value, rotate = word & 255, ((word >> 8) & 15) * 2
        return ((value >> rotate) | (value << (32 - rotate))) & 0xffffffff if rotate else value
    data = path.read_bytes()
    for plt, symbol in expected.items():
        a, b, c = struct.unpack_from('<III', data, plt - DELTA)
        assert a & 0xfffff000 == 0xe28fc000
        assert b & 0xfffff000 == 0xe28cc000
        assert c & 0xfffff000 == 0xe5bcf000
        got = plt + 8 + immediate(a) + immediate(b) + (c & 0xfff)
        assert targets[got] == symbol, (hex(plt), hex(got), targets[got])


# The sysfs prefix includes the 'x'; guard the parser offset with actual snapshots.
needle = '[0x10003200]0x'
assert len(needle) == 14
assert 'adds r0,#14' in ASM.read_text()
for snapshot in (ROOT / 'round3-evidence/startup-audit-20260930').glob('*regs.txt'):
    data = snapshot.read_text()
    start = data.index(needle) + len(needle)
    value = int(data[start:start + 8], 16)
    assert value == 0xc0, (snapshot, value)

blob = bytearray(SOURCE.read_bytes())
assert hashlib.sha256(blob).hexdigest() == SOURCE_SHA
verify_plt_targets(SOURCE)
assert blob[SITE_VA - DELTA:SITE_VA - DELTA + 4] == bytes.fromhex('32f0c3fa')
assert not any(blob[HOOK_VA - DELTA:HOOK_VA - DELTA + 0x170])
with tempfile.TemporaryDirectory(prefix='ac3-running-n1-') as tmpdir:
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
assert len(hook) <= 0x170
blob[HOOK_VA - DELTA:HOOK_VA - DELTA + len(hook)] = hook
blob[SITE_VA - DELTA:SITE_VA - DELTA + 4] = thumb_bl(SITE_VA, HOOK_VA)
TARGET.write_bytes(blob)
print(TARGET, hashlib.sha256(blob).hexdigest(), 'hook bytes', len(hook))
