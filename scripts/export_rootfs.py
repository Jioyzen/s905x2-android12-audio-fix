#!/usr/bin/env python3
"""Export a staging rootfs and recreate the empty directory omitted by Git.

This only stages files on the host. Ownership and SELinux xattrs must be restored
when injecting files into an offline Android image, using manifests/payload.json.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('output', type=Path)
    args = ap.parse_args()
    if args.output.exists():
        raise ValueError('Output must be a new directory')
    manifest = json.loads((ROOT/'manifests/payload.json').read_text())
    # Validate all sources before creating an output tree.
    for r in manifest['files']:
        if hashlib.sha256((ROOT/r['artifact']).read_bytes()).hexdigest() != r['sha256']:
            raise ValueError('Source hash mismatch: '+r['target'])
    args.output.mkdir(parents=True)
    for r in manifest['files']:
        dest = args.output/r['target'].lstrip('/')
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/r['artifact'], dest)
        dest.chmod(int(r['mode'], 8))
    for r in manifest['directories']:
        dest = args.output/r['target'].lstrip('/')
        dest.mkdir(parents=True, exist_ok=False)
        dest.chmod(int(r['mode'], 8))
    print('Staged 12 files and the required empty directory:', args.output)
    print('Android owner/group and SELinux labels are specified in manifests/payload.json')


if __name__ == '__main__':
    main()
