"""Independent T03 raw protocol vectors; invokes actual firmware dispatcher."""
from pathlib import Path
import struct
import os
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]

# Table oracle, independent from production CRC and implementation harness.
def crc16(data):
    table=[]
    for value in range(256):
        for _ in range(8):
            value=(value>>1)^0xa001 if value&1 else value>>1
        table.append(value)
    crc=0xffff
    for byte in data:
        crc=(crc>>8)^table[(crc^byte)&255]
    return struct.pack('<H',crc)


def frame(command,payload=b'',address=0x20000000):
    data=bytes.fromhex('a55a01')+bytes([command])+struct.pack('<HIH',0x8765,address,len(payload))+payload
    return data+crc16(data)

@pytest.fixture(scope='module')
def driver():
    fw_path=os.environ.get('POWERSCOPE_TEST_FW')
    cc_path=os.environ.get('POWERSCOPE_TEST_HOST_CC')
    if not fw_path or not cc_path:
        pytest.skip('set POWERSCOPE_TEST_FW and POWERSCOPE_TEST_HOST_CC explicitly')
    fw=Path(fw_path);cc=Path(cc_path)
    if not cc.exists() or not (fw/'user/source/debug_monitor_core.c').exists():
        pytest.skip('explicit T03 worktree and host compiler unavailable')
    output=ROOT/'build/t03-review.exe'
    subprocess.run([str(cc),'-std=c11','-Wall','-Wextra','-Werror','-Wno-error=unused-but-set-variable',
                    '-Itests/firmware_ns5039',f'-I{fw}/user/include',f'-I{fw}/user/source',f'-I{fw}/ns800rt/common',
                    '-include','tests/firmware_ns5039/address_seam.h','tests/firmware_ns5039/review_driver.c',
                    str(fw/'user/source/wave_codec.c'),'-o',str(output)],cwd=ROOT,check=True,capture_output=True)
    def run(*requests):
        lines=subprocess.check_output([str(output),*[r.hex() for r in requests]],text=True).splitlines()
        return [bytes.fromhex(line) for line in lines]
    return run


def check(response,status,command=0xff,payload=None):
    assert response[:3]==bytes.fromhex('a55a01')
    assert response[3]==command and response[4:6]==bytes.fromhex('6587')
    assert response[6]==status
    assert struct.unpack('<H',response[7:9])[0]==len(response)-11
    assert response[-2:]==crc16(response[:-2])
    if payload is not None:assert response[9:-2]==payload


def test_read_boundary_independent(driver):
    assert crc16(b'123456789')==bytes.fromhex('374b')
    requests=[frame(1,bytes([length])) for length in (181,182,192,193,0)]
    replies=driver(*requests)
    check(replies[0],0,1,bytes(i^0x5a for i in range(181)))
    assert len(replies[0])==192
    for reply in replies[1:]:check(reply,4,payload=b'')


@pytest.mark.parametrize('address',[0x0807ffff,0x2000ffff,0x2013ffff,0xffffffff,0])
def test_no_crossing_or_overflow(driver,address):
    check(driver(frame(1,b'\x02',address))[0],3,payload=b'')


def test_bad_frames(driver):
    valid=frame(1,b'\x04')
    bad=valid[:-1]+bytes([valid[-1]^1])
    replies=driver(valid[:13],valid[:-1],bad)
    assert replies[0]==b''
    check(replies[1],4);check(replies[2],1)


def test_batch_128_not_sample_64(driver):
    payload=bytes([16])+b''.join(struct.pack('<IB',0x20000000+i*8,8) for i in range(16))
    check(driver(frame(3,payload))[0],0,3,bytes(i^0x5a for i in range(128)))
    check(driver(frame(3,bytes([17])+payload[1:]+struct.pack('<IB',0x20000100,8)))[0],4)


def sample(items,size=4):
    return struct.pack('<BIB',0,100000,items)+b''.join(struct.pack('<IBB',0x20000000+i*8,size,0) for i in range(items))


def test_sample_limits(driver):
    replies=driver(frame(4,sample(16)),frame(4,sample(17)),frame(4,sample(9,8)),frame(4,sample(8,8)))
    check(replies[0],0,4,struct.pack('<I',100000));check(replies[1],7);check(replies[2],3)
    check(replies[3],0,4,struct.pack('<I',100000))


def test_capability_bytes_exact(driver):
    response=driver(frame(7))[0];check(response,0,7)
    info=response[9:-2]
    assert len(info)==174 and len(response)==185
    assert info[94:100]==b'PSC1\x01\x50' and info[100:132]==bytes(range(32))
    advertised={i for i in range(256) if info[132+i//8]&(1<<(i%8))}
    assert advertised=={1,2,3,4,5,6,7,8,12,13,14,32,33,34,35,37,38}
    assert info[164:]==struct.pack('<HHBBBBH',192,192,16,2,16,64,25)
    check(driver(frame(10))[0],6)

def test_acl_unchanged_from_baseline():
    import re
    if not os.environ.get('POWERSCOPE_TEST_FW'):
        pytest.skip('set POWERSCOPE_TEST_FW explicitly')
    fw=Path(os.environ['POWERSCOPE_TEST_FW'])
    before=subprocess.check_output(['git','-C',str(fw),'show','3469da8:user/source/debug_monitor_core.c'],text=True)
    after=(fw/'user/source/debug_monitor_core.c').read_text()
    def rules(source):
        block=source.split('static const DmWriteRule s_writeRules[] = {',1)[1].split('};',1)[0]
        return re.findall(r'&(\w+(?:\.\w+)+),\s*(-?[\d.]+)f,\s*(-?[\d.]+)f',block)
    assert len(rules(after))==9
    assert rules(before)==rules(after)


def test_dirty_snapshot_is_complete_and_reproducible(tmp_path):
    import importlib.util,io,zipfile,hashlib,json
    spec=importlib.util.spec_from_file_location('t03_identity_review',ROOT/'scripts/ns5039-build-identity.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    subprocess.run(['git','init',str(tmp_path)],check=True,capture_output=True)
    (tmp_path/'main.c').write_text('int main(void){return 0;}')
    (tmp_path/'makefile').write_text('\tarm-none-eabi-gcc -c main.c -o main.o\n\tarm-none-eabi-gcc main.o libctrl.a -o fw.elf\n')
    (tmp_path/'libctrl.a').write_bytes(b'library baseline')
    subprocess.run(['git','-C',str(tmp_path),'add','.'],check=True,capture_output=True)
    subprocess.run(['git','-C',str(tmp_path),'-c','user.email=review@example.invalid','-c','user.name=review','commit','-m','fixture'],check=True,capture_output=True)
    clean,_=module.collect(tmp_path,'arm-none-eabi review version')
    assert clean['dirty'] is False
    (tmp_path/'main.c').write_text('int main(void){return 1;}')
    (tmp_path/'untracked.h').write_text('#define REVIEW_INPUT 7')
    dirty,files=module.collect(tmp_path,'arm-none-eabi review version')
    assert dirty['dirty'] is True and 'untracked.h' in files
    archive=module.snapshot(files)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert set(z.namelist())==set(files)
        for row in dirty['inputs']:
            assert hashlib.sha256(z.read(row['path'])).hexdigest()==row['sha256']
    assert module.snapshot(files)==archive
    assert hashlib.sha256(json.dumps(clean,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).digest()!=hashlib.sha256(module.canonical(dirty)).digest()
