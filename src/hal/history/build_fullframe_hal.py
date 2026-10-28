#!/usr/bin/env python3
from pathlib import Path
import hashlib,struct,subprocess,tempfile,json
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
ROOT=Path(__file__).resolve().parent
BASE=ROOT.parents[1]/'out/hal-exoplayer-native-dtshd192.so'
OUT=ROOT/'audio.primary.amlogic-fullframe.so'
b=bytearray(BASE.read_bytes());assert hashlib.sha256(b).hexdigest()=='c9a223371f6012f5158c99991721efeb774c9a592e72b4d108633d8184c66fb7'
def branch(src,dst,link=False):
 d=dst-src-4;assert d%2==0 and -(1<<24)<=d<(1<<24)
 s=(d>>24)&1;i1=(d>>23)&1;i2=(d>>22)&1;j1=(~i1^s)&1;j2=(~i2^s)&1
 return struct.pack('<HH',0xf000|(s<<10)|((d>>12)&0x3ff),(0xd000 if link else 0x9000)|(j1<<13)|(j2<<11)|((d>>1)&0x7ff))
assert b[0x5b804-0x1000:0x5b808-0x1000]==branch(0x5b804,0x6db30)
assert b[0x3b776-0x1000:0x3b77a-0x1000]==branch(0x3b776,0x6dd90,True)
changes=[];listing=[]
for stem,start,limit,site,link in [('fullframe_core',0x6dc60,0x6dd00,0x3b776,True),('fullframe_format',0x6db98,0x6dc00,0x5b804,False)]:
 with tempfile.TemporaryDirectory() as t:
  p=Path(t)
  subprocess.run(['arm-linux-gnueabihf-as','-mthumb','-march=armv7-a','-o',str(p/'o'),str(ROOT/(stem+'.S'))],check=True)
  subprocess.run(['arm-linux-gnueabihf-ld',f'-Ttext={start:#x}','-o',str(p/'e'),str(p/'o')],check=True,capture_output=True)
  assert 'There are no relocations' in subprocess.check_output(['arm-linux-gnueabihf-readelf','-r',str(p/'e')],text=True)
  subprocess.run(['arm-linux-gnueabihf-objcopy','-O','binary','-j','.text',str(p/'e'),str(p/'b')],check=True)
  code=(p/'b').read_bytes()
 assert start+len(code)<=limit and not any(b[start-0x1000:start-0x1000+len(code)])
 assert start%2==0 and 0x30a80<=start<limit<=0x6e000
 b[start-0x1000:start-0x1000+len(code)]=code;b[site-0x1000:site-0x1000+4]=branch(site,start,link)
 changes.extend([(start-0x1000,start-0x1000+len(code)),(site-0x1000,site-0x1000+4)])
 listing.extend(f'{i.address:#x}: {i.bytes.hex()} {i.mnemonic} {i.op_str}' for i in Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(code,start))
original=BASE.read_bytes()
assert all(x==y or any(lo<=i<hi for lo,hi in changes) for i,(x,y) in enumerate(zip(original,b)))
# Existing owner guard, TrueHD reopen, AC3 N1, native HD and position code preserved.
for lo,hi in [(0x6d9c0,0x6db98),(0x6dc00,0x6dc60),(0x6dd00,0x6e000)]:
 assert b[lo-0x1000:hi-0x1000]==original[lo-0x1000:hi-0x1000]
OUT.write_bytes(b);(ROOT/'hal-disassembly.txt').write_text('\n'.join(listing)+'\n')
(ROOT/'hal-manifest.json').write_text(json.dumps({'source_sha256':hashlib.sha256(original).hexdigest(),'sha256':hashlib.sha256(b).hexdigest(),'size':len(b),'changes_file_offsets':changes},indent=2)+'\n')
print(OUT,hashlib.sha256(b).hexdigest());print('\n'.join(listing))
