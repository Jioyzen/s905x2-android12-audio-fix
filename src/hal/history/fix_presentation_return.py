#!/usr/bin/env python3
"""Repair the return branch in the DTS-HD presentation-position cave."""

from pathlib import Path
import hashlib
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "out/hal-dts8v8-posdiv16.so"
OUTPUT = ROOT / "out/hal-dts8v8-posdiv16-returnfix.so"
ASM = Path(__file__).with_name("presentation-return-fix.S")
EXPECTED_SOURCE = "ee85d0e4c43d6edabdb9ae527b75add4e7dd5cd302fcd910a0a1d41a83a22dd2"
VA = 0x6DAA4
FILE_OFFSET = VA - 0x1000

original = SOURCE.read_bytes()
assert hashlib.sha256(original).hexdigest() == EXPECTED_SOURCE
assert original[FILE_OFFSET:FILE_OFFSET + 10].hex() == "40f60b01c0f204010847"

with tempfile.TemporaryDirectory() as directory:
    directory = Path(directory)
    obj = directory / "branch.o"
    elf = directory / "branch.elf"
    binary = directory / "branch.bin"
    subprocess.run(["arm-linux-gnueabihf-as", "-mthumb", "-march=armv7-a", str(ASM), "-o", str(obj)], check=True)
    subprocess.run(["arm-linux-gnueabihf-ld", f"--section-start=.text=0x{VA:x}", str(obj), "-o", str(elf)], check=True)
    subprocess.run(["arm-linux-gnueabihf-objcopy", "-O", "binary", "-j", ".text", str(elf), str(binary)], check=True)
    patch = binary.read_bytes()
    assert len(patch) == 4
    print(subprocess.check_output(["arm-linux-gnueabihf-objdump", "-d", str(elf)], text=True))

fixed = bytearray(original)
fixed[FILE_OFFSET:FILE_OFFSET + len(patch)] = patch
fixed[FILE_OFFSET + len(patch):FILE_OFFSET + 10] = b"\x00\xbf" * 3
OUTPUT.write_bytes(fixed)
print(f"{OUTPUT}: {hashlib.sha256(fixed).hexdigest()}")
