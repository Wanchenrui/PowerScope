"""T05 independent fixture comparisons and fail-closed regressions."""
import hashlib
import json
import os
from pathlib import Path
from dataclasses import replace
import pytest

from power_scope.config.device_pack import DeviceCatalog, PARAMETERS, verify_manifest
from power_scope.config.device_profile import load_profile
from power_scope.debug.elf_parser import ELFParser, ElfVariable

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def profile():
    return load_profile(str(ROOT / 'power_scope/profiles/ns800rt_smoke.yaml'))

@pytest.fixture
def symbols():
    path = os.environ.get('POWERSCOPE_TEST_ELF')
    if not path:
        pytest.skip('explicit POWERSCOPE_TEST_ELF required')
    fixture = json.loads((ROOT / 'tests/fixtures/c01_20260821_addresses.json').read_text())
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == fixture['elf_sha256']
    with ELFParser(path) as parser:
        return {v.name: v for v in parser.parse_variables()}


def test_catalog_independent_18_fixture(profile, symbols):
    catalog = DeviceCatalog(profile, symbols)
    expected = json.loads((ROOT / 'tests/fixtures/c01_20260821_addresses.json').read_text())['addresses']
    assert len(catalog.parameters) == 18
    for alias, d in catalog.parameters.items():
        assert d.address == int(expected[alias], 16)
        assert (d.dtype, d.byte_size, d.type_source.value) == ('<f4', 4, 'dwarf')
        assert not d.writable and not d.readable and not d.tuning_verified
    report = catalog.report()
    assert (report['acl_count'], report['denied_count']) == (8, 10)
    assert all(set(('resolved','readable','acl','effect','tunable')) <= row.keys() for row in report['parameters'])
    assert all(not row['tunable'] for row in report['parameters'])
    assert all('commented' in d.effect_condition for a,d in catalog.parameters.items() if a.startswith('inv_curr_'))


def test_exact_acl_not_display_range(profile, symbols):
    report = DeviceCatalog(profile, symbols).report()
    allowed = {r['alias'] for r in report['parameters'] if r['acl']}
    assert allowed == {'inv_curr_pri_kp','inv_curr_pri_ki','inv_curr_phase_kp','inv_curr_phase_ki','inv_volt_kp','inv_volt_ki','urms_kp','urms_ki'}
    d = next(r for r in report['parameters'] if r['alias']=='inv_volt_kp')
    assert d['display_range'] == [0,.1] and d['write_range'] == (-100,100)


def test_pll_diagnostic_and_invalidation(profile, symbols):
    catalog = DeviceCatalog(profile, symbols)
    assert not catalog.subscription_allowed('pll_phase')
    assert any('pllPhase' in s for s in catalog.diagnostics)
    assert catalog.subscription_allowed('inv_volt_kp')
    catalog.invalidate()
    assert not catalog.parameters and not catalog.subscription_allowed('inv_volt_kp')


def test_unknown_type_and_changed_binding_deny(profile):
    alias, path, *_ = PARAMETERS[0]
    untrusted = ElfVariable(path, 0x20000004, 4, 'float')
    assert DeviceCatalog(profile, {path:untrusted}).parameters[alias].address is None
    trusted = replace(untrusted,dwarf_verified=True)
    assert DeviceCatalog(profile,{path:trusted}).parameters[alias].address is not None
    profile.variables = [replace(v,elf_symbol='invented.kp') if v.name==alias else v for v in profile.variables]
    assert DeviceCatalog(profile,{path:trusted}).parameters[alias].address is None


def test_ess_does_not_inherit_ns_and_old_yaml(profile, symbols):
    ess = load_profile(str(ROOT/'power_scope/profiles/ess_storage.yaml'))
    assert not DeviceCatalog(ess,symbols).parameters
    profile.device_pack = ''
    assert not DeviceCatalog(profile,symbols).parameters


@pytest.mark.parametrize('data', [{}, {'schema_version':1,'status':'BUILD_PENDING'}, {'schema_version':1,'status':'BUILT','model':'wrong','device_pack_version':'1'}])
def test_manifest_malformed_or_pending_denied(tmp_path,data):
    p=tmp_path/'manifest.json'; p.write_text(json.dumps(data))
    result=verify_manifest(p,tmp_path/'no.elf',bytes(32),'ns5039-v1')
    assert not result.verified and result.errors

def _elf_with_build_id(build_id):
    import struct
    names=b'\0.shstrtab\0.powerscope_build_id\0'
    data=bytearray(52)+names+build_id
    shoff=len(data)
    data.extend(bytes(40))
    data.extend(struct.pack('<10I',1,3,0,0,52,len(names),0,0,1,0))
    data.extend(struct.pack('<10I',11,1,2,0x08000000,52+len(names),32,0,0,4,0))
    data[:52]=struct.pack('<16sHHIIIIIHHHHHH',b'\x7fELF\x01\x01\x01'+bytes(9),2,40,1,0,0,shoff,0,52,0,0,40,3,1)
    return bytes(data)

@pytest.fixture
def manifest_artifacts(tmp_path):
    from power_scope.config.device_pack import sha256_file
    lib=tmp_path/'ctrl.a';lib.write_bytes(b'fixture library')
    library={'path':'ctrl.a','sha256':sha256_file(lib)}
    inputs={'schema_version':1,'model':'NS800RT5039','fw_commit':'a'*40,'dirty':True,
            'inputs':[{'path':'main.c','sha256':hashlib.sha256(b'fixture source').hexdigest()}], 'toolchain':{'version':'fixture'},
            'compile_options':[],'link_options':[],'static_libraries':[library]}
    build_id=hashlib.sha256(json.dumps(inputs,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).digest()
    elf=tmp_path/'fw.elf';elf.write_bytes(_elf_with_build_id(build_id))
    binary=tmp_path/'fw.bin';binary.write_bytes(b'fixture bin')
    import zipfile
    snap=tmp_path/'source.tar'
    with zipfile.ZipFile(snap,'w') as z:
        z.writestr('main.c',b'fixture source')
    m={'schema_version':1,'status':'BUILT','model':'NS800RT5039','device_pack_version':'1',
       'build_id':build_id.hex(),'fw_commit':'a'*40,'pc_commit':'b'*40,'build_inputs':inputs,
       'static_libraries':[library],'source_snapshot':{'path':'source.tar','sha256':sha256_file(snap)},
       'artifacts':{'elf':{'path':'fw.elf','sha256':sha256_file(elf)},'bin':{'path':'fw.bin','sha256':sha256_file(binary)}}}
    path=tmp_path/'manifest.json';path.write_text(json.dumps(m))
    return path,elf,build_id,m


def test_manifest_full_binding_and_reject_changed_artifacts(manifest_artifacts):
    path,elf,build_id,m=manifest_artifacts
    assert verify_manifest(path,elf,build_id,'ns5039-v1').verified
    assert not verify_manifest(path,elf,bytes(32),'ns5039-v1').verified
    for filename in ['ctrl.a','fw.bin','source.tar','fw.elf']:
        artifact=path.parent/filename;original=artifact.read_bytes()
        artifact.write_bytes(original+b'changed')
        assert not verify_manifest(path,elf,build_id,'ns5039-v1').verified
        artifact.write_bytes(original)
    m['device_pack_version']='unknown';path.write_text(json.dumps(m))
    assert not verify_manifest(path,elf,build_id,'ns5039-v1').verified


def test_manifest_truncated_elf_is_rejection(manifest_artifacts):
    from power_scope.config.device_pack import sha256_file
    path,elf,build_id,m=manifest_artifacts
    elf.write_bytes(b'bad elf')
    m['artifacts']['elf']['sha256']=sha256_file(elf);path.write_text(json.dumps(m))
    assert not verify_manifest(path,elf,build_id,'ns5039-v1').verified


def test_parser_same_mtime_reopens_content(tmp_path):
    first=tmp_path/'fw.elf';first.write_bytes(_elf_with_build_id(bytes(32)))
    with ELFParser(first) as parser:
        parser.parse_variables()
        stamp=first.stat()
        first.write_bytes(_elf_with_build_id(b'x'*32))
        os.utime(first,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        parser.parse_variables()
        assert parser.elf.get_section_by_name('.powerscope_build_id').data()==b'x'*32

def test_window_consumes_catalog_and_invalidates(qapp, profile, symbols):
    from types import SimpleNamespace
    from power_scope.ui.main_window import MainWindow
    profile.elf_file = ''
    window = MainWindow(profile)
    try:
        window._on_elf_loaded(SimpleNamespace(variables=list(symbols.values()),path=os.environ['POWERSCOPE_TEST_ELF'],load_token=window._var_view._elf_load_token))
        old=window._catalog
        assert len(old.parameters)==18
        assert window._resolve_channel('pll_phase') is None
        assert window._resolve_channel('inv_volt_kp') is not None
        window._session.invalidate('test reconnect')
        assert not old.parameters
        assert not window._profile_channels and not window._extra_channels
        assert not any(d.writable for d in window._catalog.parameters.values())
        window.apply_profile(profile)
        assert not window._symbols and window._catalog_elf_path == ''
        assert all(d.address is None for d in window._catalog.parameters.values())
    finally:
        window.close()

def test_snapshot_cannot_self_declare_unrelated_sources(manifest_artifacts):
    import zipfile
    from power_scope.config.device_pack import sha256_file
    path,elf,build_id,m=manifest_artifacts
    snap=path.parent/'source.tar'
    with zipfile.ZipFile(snap,'w') as archive:
        archive.writestr('main.c',b'unrelated source')
    m['source_snapshot']['sha256']=sha256_file(snap)
    path.write_text(json.dumps(m))
    result=verify_manifest(path,elf,build_id,'ns5039-v1')
    assert not result.verified and 'source snapshot content mismatch' in result.errors
