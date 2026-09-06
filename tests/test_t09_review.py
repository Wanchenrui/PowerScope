"""Independent T09 raw firmware path and exact final build review."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def review_driver():
    fw=Path(os.environ['POWERSCOPE_TEST_FW'])
    cc=Path(os.environ['POWERSCOPE_TEST_HOST_CC'])
    output=ROOT/'build/t09-independent.exe'
    result=subprocess.run([str(cc),'-std=c11','-Wall','-Wextra','-Werror',
        '-Wno-error=unused-but-set-variable','-Itests/firmware_ns5039',
        f'-I{fw}/user/include',f'-I{fw}/user/source',f'-I{fw}/ns800rt/common',
        '-include','tests/firmware_ns5039/address_seam.h',
        'tests/firmware_ns5039/t09_review_driver.c',str(fw/'user/source/wave_codec.c'),
        '-o',str(output)],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    def run(scenario,command=2,bits='3f000000'):
        text=subprocess.check_output([str(output),scenario,str(command),bits],text=True).split()
        return [int(v,16 if index==1 else 10) for index,v in enumerate(text)]
    return run


@pytest.mark.parametrize('command',[2,8])
@pytest.mark.parametrize('scenario,status',[
    ('idle',0),('run',5),('stopping',5),('unknown',5),('requested_on',5),
    ('pending_pwm',5),('bad_pwm',5),('unknown_consumer',5),
    ('fault',6),('protect_unknown',6),('race',6)])
def test_independent_state_vectors(review_driver,scenario,status,command):
    actual,bits,mask,disable,restore,generation,last=review_driver(scenario,command)
    assert actual==last==status
    assert bits==(0x3f000000 if status==0 else 0x3e800000)
    assert mask==0 and disable==restore and generation%2==0


@pytest.mark.parametrize('bits',['7fc00000','7f800000','ff800000','7f7fffff'])
def test_numeric_rejection_precedes_runtime_gate(review_driver,bits):
    status,value,mask,disable,restore,generation,last=review_driver('idle',8,bits)
    assert status==last==6 and value==0x3e800000
    # Only setup refreshed observation. Rejected values never enter commit gate.
    assert disable==restore==1


def test_mask_restore_generation_wrap_and_scratch_separation(review_driver):
    masked=review_driver('masked')
    assert masked[0]==0 and masked[2]==1
    wrapped=review_driver('wrap')
    assert wrapped[0]==0 and wrapped[5]==0
    scratch=review_driver('scratch_fault')
    assert scratch[0]==0 and scratch[1]==0x3e800000 and scratch[3]==1


def test_final_target_and_current_sources_match():
    from elftools.elf.elffile import ELFFile
    from power_scope.config.device_pack import verify_manifest
    target=ROOT/'build/t09-identity-final-v2'
    manifest=target/'manifest.json'
    payload=json.loads(manifest.read_text(encoding="utf-8"))
    assert hashlib.sha256(manifest.read_bytes()).hexdigest()=='b7b83b05d5d5623f35b93a32dbe2534bdf9002c07b190f41cc56c7912eeb5270'
    elf_path=target/'artifacts/firmware.elf'
    with elf_path.open('rb') as stream:
        elf=ELFFile(stream)
        embedded=elf.get_section_by_name('.powerscope_build_id').data()
        symbols=elf.get_section_by_name('.symtab')
        assert symbols.get_symbol_by_name('g_dm_control_observation')[0]['st_size']==48
        assert symbols.get_symbol_by_name('g_dm_last_write_status')[0]['st_size']==4
    assert embedded.hex()=='5145f8a1f726c7c0daf94044928dd90ecb6d6ac180a52fa4da275c5109841c7a'
    # Offline embedded identity, NOT a board observation.
    verified=verify_manifest(manifest,elf_path,embedded,'ns5039-v1')
    assert verified.verified,verified.errors
    assert not verify_manifest(manifest,elf_path,b'z'*32,'ns5039-v1').verified
    fw=Path(os.environ['POWERSCOPE_TEST_FW'])
    inputs=payload['build_inputs']['inputs']
    assert len(inputs)==342
    assert all(hashlib.sha256((fw/item['path']).read_bytes()).hexdigest()==item['sha256'] for item in inputs)
