#!/usr/bin/env python3
"""Build the SPDIF packer and system OMX plugin offline using the archived sources.

ANDROID_NDK_HOME must point to NDK 28.2.13676358. The frozen FFmpeg static
libraries are supplied along with their complete source archives and generated
headers. --relink-frozen reuses the two archived adapter objects. Rebuild output
is a development artifact until its hashes and playback have been revalidated.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    subprocess.run([str(x) for x in args], check=True)


def source_tree(version):
    base = ROOT/'_build/upstream'
    dest = base/('FFmpeg-'+version)
    if not dest.exists():
        base.mkdir(parents=True, exist_ok=True)
        with tarfile.open(ROOT/'third_party'/f'FFmpeg-{version}-source.tar.xz') as archive:
            archive.extractall(base, filter='data')
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ndk', type=Path, default=os.environ.get('ANDROID_NDK_HOME'))
    ap.add_argument('--relink-frozen', action='store_true')
    ap.add_argument('--spdif-ffmpeg-libs', type=Path, default=ROOT/'src/spdif/frozen-ffmpeg')
    ap.add_argument('--decoder-ffmpeg-libs', type=Path, default=ROOT/'src/decoder/frozen-ffmpeg')
    args = ap.parse_args()
    if args.ndk is None:
        ap.error('Set ANDROID_NDK_HOME or provide --ndk')
    tool = args.ndk/'toolchains/llvm/prebuilt/linux-x86_64/bin'
    cc, cxx = tool/'armv7a-linux-androideabi26-clang', tool/'armv7a-linux-androideabi26-clang++'
    if not cc.is_file() or not cxx.is_file():
        ap.error('Expected Linux x86_64 NDK ARMv7 compilers')
    out = ROOT/'_build/native'; out.mkdir(parents=True, exist_ok=True)
    s = ROOT/'src/spdif'; d = ROOT/'src/decoder'
    hd_object = s/'ffmpeg_hdpack.o'
    if not args.relink_frozen:
        hd_object = out/'ffmpeg_hdpack.o'
        run([cc, '-O2', '-fPIC', '-I'+str(s/'frozen-ffmpeg'), '-I'+str(source_tree('n8.1.3')),
             '-I'+str(s/'include'), '-c', s/'ffmpeg_hdpack.c', '-o', hd_object])
    packer = out/'libdroidaudiospdif.so'
    # Preserve the __FILE__ diagnostic string embedded in the frozen packer.
    diagnostic_map = '-ffile-prefix-map='+str(s/'FrameScanner.cpp')+'=/home/zeng/cebox/offline-build/v24-hd-packer/spdif/FrameScanner.cpp'
    run([cxx, '-fPIC', '-O2', '-nostdlib++', '-fno-exceptions', '-fno-rtti', diagnostic_map,
         '-fvisibility=default', '-w', '-I'+str(s/'include'), '-I'+str(s),
         '-shared', '-Wl,-soname,libdroidaudiospdif.so', '-Wl,--gc-sections',
         '-Wl,--no-undefined', '-L'+str(s/'libstub'), '-o', packer,
         s/'SPDIFEncoderHD.cpp', s/'AC3FrameScanner.cpp', s/'DTSFrameScanner.cpp',
         s/'FrameScanner.cpp', s/'BitFieldParser.cpp', s/'abi_alias.S', hd_object,
         '-Wl,--start-group', *[args.spdif_ffmpeg_libs/(x+'.a') for x in ['libavformat', 'libavcodec', 'libavutil']],
         '-Wl,--end-group', '-lc++', '-llog', '-lm'])
    run([tool/'llvm-strip', '--strip-unneeded', packer])
    omx_object = d/'SurroundDecoder.o'
    if not args.relink_frozen:
        omx_object = out/'SurroundDecoder.o'
        run([cxx, '-std=gnu++17', '-O2', '-fPIC', '-fno-exceptions', '-fno-rtti',
             '-nostdlib++', '-I'+str(d/'include'), '-I'+str(d/'frozen-ffmpeg'),
             '-I'+str(source_tree('n6.1.1')), '-c', d/'SurroundDecoder.cpp', '-o', omx_object])
    plugin = out/'libstagefrighthw.so'
    run([cxx, '-shared', '-nostdlib++', '-Wl,--exclude-libs,ALL',
         '-Wl,--version-script='+str(d/'exports.map'), '-Wl,-soname,libstagefrighthw.so',
         '-Wl,--no-undefined', omx_object, '-Wl,--start-group',
         *[args.decoder_ffmpeg_libs/(x+'.a') for x in ['libavcodec', 'libswresample', 'libavutil']],
         '-Wl,--end-group', '-L'+str(d/'libstub'), '-lstagefright_softomx',
         '-lstagefright_foundation', '-lutils', '-lc++', '-llog', '-ldl', '-lm', '-o', plugin])
    manifest = json.loads((ROOT/'manifests/payload.json').read_text())['files']
    results = []
    for file, target in [(packer, '/vendor/lib/libdroidaudiospdif.so'), (plugin, '/vendor/lib/libstagefrighthw.so')]:
        sha = hashlib.sha256(file.read_bytes()).hexdigest()
        frozen = next(x['sha256'] for x in manifest if x['target'] == target)
        results.append({'target': target, 'size': file.stat().st_size, 'sha256': sha,
                        'frozen_sha256': frozen, 'byte_identical': sha == frozen})
        print(file.name, sha, 'identical to frozen payload:', sha == frozen)
    (out/'build-results.json').write_text(json.dumps({'relink_frozen': args.relink_frozen, 'files': results}, indent=2)+'\n')


if __name__ == '__main__':
    main()
