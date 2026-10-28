#!/usr/bin/env python3
"""Fetch the pinned Android 12 headers used to link the device's OMX base."""
import base64
import concurrent.futures
import re
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parent / 'include'
tag = 'android-12.0.0_r34'
routes = {
    'utils/': ('system/core', 'libutils/include/'),
    'cutils/': ('system/core', 'libcutils/include/'),
    'log/': ('system/logging', 'liblog/include/'),
    'android-base/': ('system/libbase', 'include/'),
    'media/stagefright/foundation/': ('frameworks/av', 'media/libstagefright/foundation/include/'),
    'media/stagefright/omx/': ('frameworks/av', 'media/libstagefright/omx/include/'),
    'media/hardware/': ('frameworks/native', 'headers/media_plugin/'),
    'OMX_': ('frameworks/native', 'headers/media_plugin/media/openmax/'),
}

def route(name):
    return next((v for k, v in routes.items() if name.startswith(k)), None)

def fetch(name):
    dest = root / name
    if dest.exists():
        return name, dest.read_text(), None
    repo, prefix = route(name)
    url = f'https://android.googlesource.com/platform/{repo}/+/{tag}/{prefix}{name}?format=TEXT'
    try:
        data = base64.b64decode(urllib.request.urlopen(url, timeout=20).read())
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return name, data.decode(), None
    except Exception as e:
        return name, '', str(e)

todo = {'media/hardware/OMXPluginBase.h', 'media/stagefright/omx/SimpleSoftOMXComponent.h'}
seen = set()
while todo:
    current = todo - seen
    if not current:
        break
    seen.update(current)
    todo = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for name, text, error in pool.map(fetch, sorted(current)):
            if error:
                print('FAILED', name, error, flush=True)
                continue
            print('OK', name, flush=True)
            for delim, inc in re.findall(r'^\s*#\s*include\s*([<\"])([^>\"]+)[>\"]', text, re.M):
                if delim == '"' and not route(inc):
                    inc = str(Path(name).parent / inc)
                if route(inc):
                    todo.add(inc)
