"""Identity counterexamples use small repositories, without synthetic ARM success."""
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import zipfile

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/ns5039-build-identity.py'
spec = importlib.util.spec_from_file_location('ns5039_identity', SCRIPT)
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


def test_canonical_snapshot_covers_dirty_and_untracked_inputs(tmp_path):
    fw = tmp_path / 'firmware'; fw.mkdir()
    for name, contents in {
        'user/include/control.h': b'original\n',
        'Debug/makefile': b'\tarm-none-eabi-gcc -mcpu=cortex-m7 -o firmware.elf\n',
        'Debug/source.mk': b'\tarm-none-eabi-gcc -mcpu=cortex-m7 -c control.c\n',
        'cbb/control.a': b'library-input',
    }.items():
        p = fw / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(contents)
    def git(*args):
        subprocess.run(['git', '-C', str(fw), *args], check=True, capture_output=True)
    git('init'); git('add', '.'); git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')
    first, files = identity.collect(fw, 'toolchain-version')
    assert not first['dirty']
    assert identity.canonical({'z': 1, 'a': 2}) == b'{"a":2,"z":1}'
    archive = identity.snapshot(files)
    assert archive == identity.snapshot(files)
    (fw / 'user/include/control.h').write_bytes(b'changed\n')
    (fw / 'user/include/added.h').write_bytes(b'untracked input\n')
    changed, files = identity.collect(fw, 'toolchain-version')
    assert changed['dirty'] and changed != first
    assert identity.digest(identity.canonical(changed)) != identity.digest(identity.canonical(first))
    out = tmp_path / 'identity'
    identity.prepare(SimpleNamespace(fw=fw, out=out, pc=fw, cc=None, device_pack_version='1'))
    record = json.loads((out / 'input-record.json').read_text())
    assert record['status'] == 'BUILD_PENDING'
    assert not (out / 'manifest.json').exists()
    with zipfile.ZipFile(out / 'source.zip') as snapshot:
        assert snapshot.read('user/include/added.h') == b'untracked input\n'
        assert snapshot.read('user/include/control.h') == b'changed\n'
    before, _ = identity.collect(fw, 'UNAVAILABLE')
    # Generated header and stale artifacts never feed their own identity.
    (fw / identity.GENERATED).write_text('regenerated')
    (fw / 'Debug/firmware.elf').write_bytes(b'artifact')
    after, _ = identity.collect(fw, 'UNAVAILABLE')
    assert before == after
    assert identity.digest(identity.canonical(before)) == record['build_id']
