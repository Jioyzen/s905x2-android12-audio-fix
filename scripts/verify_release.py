#!/usr/bin/env python3
"""Verify the frozen payload, originals, exact binary reconstruction and XML."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from reconstruct_binaries import reconstruct

ROOT = Path(__file__).resolve().parents[1]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def verify():
    payload = json.loads((ROOT/'manifests/payload.json').read_text())
    records = payload['files']
    require(len(records) == 12, 'Expected twelve payload files')
    require(sum(x['action'] == 'replace' for x in records) == 10, 'Expected ten replacements')
    require(sum(x['action'] == 'add' for x in records) == 2, 'Expected two additions')
    require(len({x['target'] for x in records}) == len(records), 'Duplicate target path')
    for r in records:
        data = (ROOT/r['artifact']).read_bytes()
        require(len(data) == r['size'] and hashlib.sha256(data).hexdigest() == r['sha256'], r['target'])
        require(r['uid'] == r['gid'] == 0 and r['mode'] == '0644', 'Incorrect payload ownership/mode')
        if r['action'] == 'replace':
            data = (ROOT/r['baseline']).read_bytes()
            require(len(data) == r['original_size'] and hashlib.sha256(data).hexdigest() == r['original_sha256'], 'Original mismatch: '+r['target'])
        if r['target'].endswith('.xml'):
            ET.parse(ROOT/r['artifact'])
    delta = json.loads((ROOT/'manifests/binary-deltas.json').read_text())['files']
    for r in delta:
        rel = r['target'].lstrip('/')
        require(reconstruct((ROOT/'baseline/rootfs'/rel).read_bytes(), r) == (ROOT/'artifacts/rootfs'/rel).read_bytes(), 'Binary delta mismatch')
        damaged = bytearray((ROOT/'baseline/rootfs'/rel).read_bytes()); damaged[0] ^= 1
        try:
            reconstruct(damaged, r)
        except ValueError:
            pass
        else:
            raise ValueError('Damaged original was accepted')
    old = (ROOT/'baseline/rootfs/product/etc/build.prop').read_bytes()
    new = (ROOT/'artifacts/rootfs/product/etc/build.prop').read_bytes()
    require(old.count(b'ro.af.client_heap_size_kbyte=2048') == 1, 'Unexpected original property')
    require(old.replace(b'ro.af.client_heap_size_kbyte=2048', b'ro.af.client_heap_size_kbyte=8192') == new, 'Unexpected build.prop change')
    require((ROOT/'artifacts/rootfs/vendor/lib/libstagefrighthw_original.so').read_bytes() == (ROOT/'baseline/rootfs/vendor/lib/libstagefrighthw.so').read_bytes(), 'Delegated original plugin differs')
    for line in (ROOT/'SHA256SUMS').read_text().splitlines():
        expected, rel = line.split('  ', 1)
        path = ROOT/rel
        require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'Package checksum mismatch: '+rel)
    print('PASS: 12 payloads, 10 originals, 4 exact binary reconstructions, damaged-input rejection, XML, property-only change and package checksums')


if __name__ == '__main__':
    verify()
