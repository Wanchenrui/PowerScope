#!/usr/bin/env python3
"""Rebuild NS5039 in FW/powerscope-out; never touches existing Debug artifacts."""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fw',type=Path,required=True)
    p.add_argument('--cc',type=Path,required=True)
    p.add_argument('--make',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True,help='manifest/snapshot directory outside firmware')
    p.add_argument('--device-pack-version',default='1')
    a=p.parse_args()
    fw=a.fw.resolve(); out=a.out.resolve(); cc=a.cc.resolve()
    stage=fw/'powerscope-out'
    # A populated directory could contain stale objects. Refuse instead of deleting.
    if stage.exists() and any(stage.iterdir()):
        p.exit(1,'powerscope-out must be empty; select a fresh firmware worktree for a new rebuild\n')
    stage.mkdir(exist_ok=True)
    for src in (fw/'Debug').rglob('*'):
        if src.is_file() and (src.suffix=='.mk' or src.name=='makefile'):
            dst=stage/src.relative_to(fw/'Debug');dst.parent.mkdir(parents=True,exist_ok=True)
            dst.write_bytes(src.read_bytes())
    script=Path(__file__).with_name('ns5039-build-identity.py')
    subprocess.run([sys.executable,str(script),'prepare','--fw',str(fw),'--out',str(out),'--pc',str(Path(__file__).resolve().parent.parent),'--cc',str(cc),'--device-pack-version',a.device_pack_version],check=True)
    env=os.environ.copy();env['PATH']=str(cc.parent)+os.pathsep+env.get('PATH','')
    subprocess.run([str(a.make.resolve()),'-C',str(stage),'-B','-j2','main-build'],env=env,check=True)
    elf=stage/'C01_2in1_20260821_ongridStable.elf'; binary=elf.with_suffix('.bin')
    subprocess.run([str(cc.with_name('arm-none-eabi-objcopy.exe')),'-O','binary',str(elf),str(binary)],check=True)
    subprocess.run([str(cc.with_name('arm-none-eabi-size.exe')),str(elf)],check=True)
    subprocess.run([sys.executable,str(script),'finalize','--fw',str(fw),'--out',str(out),'--elf',str(elf),'--bin',str(binary),'--map',str(elf.with_suffix('.map'))],check=True)

if __name__=='__main__':
    main()
