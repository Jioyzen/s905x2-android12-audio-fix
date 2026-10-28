#!/usr/bin/env python3
"""Recreate the four patched firmware binaries from verified original files.

The delta records include every byte edit, including ELF layout changes. This
reproduces the frozen artifacts; it does not infer patches for another firmware.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def reconstruct(original, record):
    require(len(original) == record['input_size'], 'Input size mismatch')
    require(hashlib.sha256(original).hexdigest() == record['input_sha256'], 'Input SHA256 mismatch')
    data = bytearray(original)
    data.extend(b'\0' * max(0, record['output_size'] - len(data)))
    last = 0
    for edit in record['edits']:
        at = edit['offset']
        before, after = bytes.fromhex(edit['before_hex']), bytes.fromhex(edit['after_hex'])
        require(at >= last and len(before) == len(after), 'Overlapping or resizing byte edits')
        require(data[at:at+len(before)] == before, f'Original instruction mismatch at {at:#x}')
        data[at:at+len(after)] = after
        last = at + len(after)
    data = bytes(data[:record['output_size']])
    require(hashlib.sha256(data).hexdigest() == record['output_sha256'], 'Reconstructed SHA256 mismatch')
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-root', type=Path, default=ROOT/'baseline/rootfs')
    ap.add_argument('--output-root', type=Path, default=ROOT/'_build/reconstructed')
    args = ap.parse_args()
    require(args.output_root.resolve() != args.input_root.resolve(), 'Input/output roots must differ')
    require(args.output_root.resolve() != (ROOT/'artifacts/rootfs').resolve(), 'Do not overwrite frozen artifacts')
    files = json.loads((ROOT/'manifests/binary-deltas.json').read_text())['files']
    for record in files:
        rel = record['target'].lstrip('/')
        output = args.output_root/rel
        output.parent.mkdir(parents=True, exist_ok=True)
        data = reconstruct((args.input_root/rel).read_bytes(), record)
        require(data == (ROOT/'artifacts/rootfs'/rel).read_bytes(), 'Frozen artifact mismatch')
        output.write_bytes(data)
        print(record['target'], record['output_sha256'])


if __name__ == '__main__':
    main()
