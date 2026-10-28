#!/usr/bin/env python3
"""Read the exact reference firmware, expand sparse super, verify LP and extract files.

Uses only Python's standard library and debugfs. Never accesses a device or network.
All intermediate images stay in the explicitly selected output directory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BLOCK = 8 * 1024 * 1024


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def stream_copy(src, dst, count, digest=None):
    while count:
        b = src.read(min(count, BLOCK))
        require(bool(b), 'Unexpected end of image')
        dst.write(b)
        if digest is not None:
            digest.update(b)
        count -= len(b)


def expand_super(image, desc, output):
    # Hash precisely the Amlogic container's known super item before expanding it.
    h = hashlib.sha256()
    with image.open('rb') as f:
        f.seek(desc['offset'])
        left = desc['size']
        while left:
            b = f.read(min(left, BLOCK))
            require(bool(b), 'Truncated super item')
            h.update(b)
            left -= len(b)
    require(h.hexdigest() == desc['sha256'], 'Container super-item hash mismatch')
    with image.open('rb') as f, output.open('xb') as out:
        f.seek(desc['offset'])
        magic, major, minor, hs, cs, bs, blocks, chunks, crc = struct.unpack('<I4H4I', f.read(28))
        require(magic == 0xed26ff3a and major == 1 and hs >= 28 and cs >= 12,
                'Unsupported Android sparse header')
        require(0 < bs <= BLOCK and bs % 4 == 0, 'Invalid sparse block size')
        f.seek(hs - 28, 1)
        logical = 0
        for _ in range(chunks):
            typ, reserved, nblocks, total = struct.unpack('<HHII', f.read(12))
            f.seek(cs - 12, 1)
            count = nblocks * bs
            payload = total - cs
            require(payload >= 0 and logical + count <= blocks * bs, 'Invalid sparse chunk')
            if typ == 0xcac1:
                require(payload == count, 'RAW sparse size mismatch')
                stream_copy(f, out, count)
                logical += count
            elif typ == 0xcac2:
                require(payload == 4, 'FILL sparse size mismatch')
                word = f.read(4)
                if word == b'\0' * 4:
                    out.seek(count, 1)
                else:
                    buf = word * (BLOCK // 4)
                    left = count
                    while left:
                        out.write(buf[:min(left, BLOCK)])
                        left -= min(left, BLOCK)
                logical += count
            elif typ == 0xcac3:
                require(payload == 0, 'DONT_CARE sparse size mismatch')
                out.seek(count, 1)
                logical += count
            elif typ == 0xcac4:
                require(payload == 4 and nblocks == 0, 'CRC sparse size mismatch')
                f.read(4)
            else:
                raise ValueError(f'Unknown sparse chunk {typ:#x}')
        require(logical == blocks * bs, 'Sparse expanded size mismatch')
        require(f.tell() <= desc['offset'] + desc['size'], 'Sparse item overruns container entry')
        out.truncate(logical)


def read_lp(raw):
    with raw.open('rb') as f:
        data = f.read(1024 * 1024)
    geo = data[4096:8192]
    magic, size = struct.unpack_from('<II', geo)
    require(magic == 0x616c4467 and 52 <= size <= 4096, 'Invalid LP geometry')
    gh = bytearray(geo[:size]); expected = bytes(gh[8:40]); gh[8:40] = b'\0' * 32
    require(hashlib.sha256(gh).digest() == expected, 'LP geometry checksum mismatch')
    maximum, slots, lbs = struct.unpack_from('<III', geo, 40)
    # Primary slot 0 immediately follows the reserved block and two geometries.
    off = 12288
    magic, major, minor, hs = struct.unpack_from('<IHHI', data, off)
    require(magic == 0x414c5030 and 128 <= hs <= maximum, 'Invalid LP header')
    head = bytearray(data[off:off+hs]); expected = bytes(head[12:44]); head[12:44] = b'\0' * 32
    require(hashlib.sha256(head).digest() == expected, 'LP header checksum mismatch')
    ts = struct.unpack_from('<I', head, 44)[0]
    require(hs + ts <= maximum and off + hs + ts <= len(data), 'Invalid LP table bounds')
    tables = data[off+hs:off+hs+ts]
    require(hashlib.sha256(tables).digest() == head[48:80], 'LP tables checksum mismatch')
    po, pn, ps = struct.unpack_from('<III', head, 80)
    eo, en, es = struct.unpack_from('<III', head, 92)
    require(ps >= 52 and es >= 24 and po + pn * ps <= ts and eo + en * es <= ts,
            'Invalid LP table descriptors')
    extents = [struct.unpack_from('<QIQI', tables, eo+i*es) for i in range(en)]
    parts = []
    for i in range(pn):
        at = po+i*ps
        name = tables[at:at+36].split(b'\0')[0].decode('ascii')
        require(name and '/' not in name and name not in ('.', '..'), 'Invalid partition name')
        attrs, first, num, group = struct.unpack_from('<IIII', tables, at+36)
        require(first+num <= en, 'Invalid partition extent count')
        selected = []
        for sectors, typ, sector, source in extents[first:first+num]:
            require(typ == 0 and source == 0, 'Only linear single-super partitions supported')
            require((sector+sectors)*512 <= raw.stat().st_size, 'Extent overruns super')
            selected.append({'sectors': sectors, 'super_sector': sector})
        parts.append({'name': name, 'extents': selected, 'size': sum(x['sectors']*512 for x in selected)})
    return {'version': f'{major}.{minor}', 'slots': slots, 'logical_block_size': lbs, 'partitions': parts}


def inode_path(target):
    partition, relative = target.lstrip('/').split('/', 1)
    return partition, ('/system/' if partition == 'system' else '/') + relative


def debugfs(image, command):
    r = subprocess.run(['debugfs', '-R', command, str(image)], capture_output=True, text=True, check=True)
    return r.stdout + r.stderr


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('image', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    original = json.loads((ROOT/'manifests/original-image.json').read_text())
    require(args.image.is_file() and args.image.stat().st_size == original['size'], 'Original firmware size mismatch')
    require(sha(args.image) == original['sha256'], 'Original firmware SHA256 mismatch')
    args.out.mkdir(parents=True, exist_ok=False)
    raw = args.out/'super.raw.img'
    expand_super(args.image, original['super_item'], raw)
    lp = read_lp(raw)
    for p in lp['partitions']:
        expected = next(x for x in original['partitions'] if x['name'] == p['name'])
        require(expected['size'] == p['size'], 'Original partition size mismatch')
        dest = args.out/(p['name']+'.img')
        h = hashlib.sha256()
        with raw.open('rb') as f, dest.open('xb') as out:
            for ex in p['extents']:
                f.seek(ex['super_sector']*512)
                stream_copy(f, out, ex['sectors']*512, h)
        p['sha256'] = h.hexdigest()
        require(p['sha256'] == expected['sha256'], f"Original {p['name']} hash mismatch")
        print(p['name'], p['sha256'], flush=True)
    targets = [x['target'] for x in json.loads((ROOT/'manifests/payload.json').read_text())['files']]
    targets += ['/vendor/lib/libamaudioutils.so']
    report = {'original_sha256': original['sha256'], 'lp': lp, 'files': []}
    for target in targets:
        partition, inode = inode_path(target)
        fs = args.out/(partition+'.img')
        dest = args.out/'rootfs'/target.lstrip('/')
        dest.parent.mkdir(parents=True, exist_ok=True)
        stat = debugfs(fs, f'stat {inode}')
        record = {'target': target, 'inode_path': inode, 'exists': 'Inode:' in stat}
        if record['exists']:
            result = debugfs(fs, f'dump {inode} "{dest}"')
            require(dest.is_file(), f'Cannot extract {target}: {result}')
            record.update(size=dest.stat().st_size, sha256=sha(dest), stat=stat)
        report['files'].append(record)
    (args.out/'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('Verified reference firmware and extracted original files:', args.out)


if __name__ == '__main__':
    main()
