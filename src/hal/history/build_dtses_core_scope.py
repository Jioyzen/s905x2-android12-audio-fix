#!/usr/bin/env python3
import hashlib,struct,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'out/hal-ac3-running-n1-latch.so'
target=ROOT/'out/hal-ac3-n1-dtses-core.so'
ASM=Path(__file__).with_name('dtses_core_scope.S')
DELTA=0x1000

def branch(src,dst):
 d=dst-src-4;assert d%2==0 and -(1<<24)<=d<(1<<24)
 s=(d>>24)&1;i1=(d>>23)&1;i2=(d>>22)&1;j1=(~i1^s)&1;j2=(~i2^s)&1
 return struct.pack('<HH',0xf000|(s<<10)|((d>>12)&0x3ff),0x9000|(j1<<13)|(j2<<11)|((d>>1)&0x7ff))

b=bytearray(source.read_bytes());assert hashlib.sha256(b).hexdigest()=='f11e2f233cf430f058ed0f14b1ef724ed006c097b2a751b6678362dc0b15845d'
assert not any(b[0x6db30-DELTA:0x6dc00-DELTA])
assert b[0x6da80-DELTA:0x6da84-DELTA]==bytes.fromhex('d4f8f801')
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);o=p/'hook.o';e=p/'hook.elf';r=p/'hook.bin'
 subprocess.run(['arm-linux-gnueabihf-as','-mthumb','-march=armv7-a','-o',str(o),str(ASM)],check=True)
 subprocess.run(['arm-linux-gnueabihf-ld','-Ttext=0x6db30','-o',str(e),str(o)],check=True,capture_output=True)
 assert 'There are no relocations' in subprocess.check_output(['arm-linux-gnueabihf-readelf','-r',str(e)],text=True)
 symbols=subprocess.check_output(['arm-linux-gnueabihf-nm',str(e)],text=True)
 guard=int(next(x.split()[0] for x in symbols.splitlines() if x.endswith(' dts_base_position_guard')),16)&~1
 subprocess.run(['arm-linux-gnueabihf-objcopy','-O','binary','-j','.text',str(e),str(r)],check=True)
 hook=r.read_bytes()
 assert len(hook)<=0xd0
 b[0x6db30-DELTA:0x6db30-DELTA+len(hook)]=hook
 b[0x5b804-DELTA:0x5b808-DELTA]=branch(0x5b804,0x6db30)
 b[0x6da80-DELTA:0x6da84-DELTA]=branch(0x6da80,guard)
 print(subprocess.check_output(['arm-linux-gnueabihf-objdump','-d',str(e)],text=True))
target.write_bytes(b);print(target,len(hook),hashlib.sha256(b).hexdigest())
