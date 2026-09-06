#!/usr/bin/env python3
"""NS5039 build identity producer. No flashing or serial access.

prepare snapshots build inputs and writes the generated header. finalize verifies
that inputs are unchanged and that the linked ELF contains the generated ID.
Paths in a final manifest resolve relative to its directory.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

GENERATED = 'user/include/powerscope_build_id.h'
OUTPUT_DIRS = {'.git', 'powerscope-out', 'powerscope-identity', '__pycache__'}
ARTIFACT_SUFFIXES = {'.elf', '.bin', '.hex', '.map', '.o', '.d', '.dis', '.siz', '.su', '.pyc'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def source_files(root):
    result = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if any(part in OUTPUT_DIRS for part in relative.parts) or relative.as_posix() == GENERATED:
            continue
        if path.is_symlink():
            raise ValueError(f'symlink build input is unsupported: {relative}')
        if path.is_file() and path.suffix.lower() not in ARTIFACT_SUFFIXES:
            result[relative.as_posix()] = path.read_bytes()
    return result


def recipes(root, linker):
    lines = []
    for path in sorted(root.rglob('*')):
        if any(part in OUTPUT_DIRS for part in path.relative_to(root).parts):
            continue
        if not path.is_file() or (path.suffix != '.mk' and path.name != 'makefile' and not path.name.startswith('makefile.')):
            continue
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.startswith('\tarm-none-eabi-gcc ') and (' -c ' not in line) == linker:
                lines.append(line.strip().replace('\\', '/'))
    return sorted(set(lines))


def collect(root, version):
    files = source_files(root)
    tracked = set(git(root, 'ls-files').splitlines())
    changed = set(git(root, 'diff', 'HEAD', '--name-only').splitlines())
    dirty = bool((set(files) - tracked) or (changed & set(files)))
    # Deleted tracked build inputs must also mark the source as dirty.
    dirty |= any(Path(p).suffix.lower() not in ARTIFACT_SUFFIXES and p != GENERATED for p in changed)
    records = [{'path': p, 'sha256': digest(data)} for p, data in files.items()]
    inputs = {
        'schema_version': 1, 'model': 'NS800RT5039',
        'fw_commit': git(root, 'rev-parse', 'HEAD'), 'dirty': bool(dirty),
        'inputs': records, 'toolchain': {'version': version},
        'compile_options': recipes(root, False), 'link_options': recipes(root, True),
        'static_libraries': [r for r in records if Path(r['path']).suffix == '.a'],
        'identity_generator_sha256': digest(Path(__file__).read_bytes()),
    }
    if not inputs['compile_options'] or not inputs['link_options'] or not inputs['static_libraries']:
        raise ValueError('missing compilation/link recipes or static libraries')
    return inputs, files


def snapshot(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, contents in files.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, contents)
    return data.getvalue()


def prepare(args):
    root, out = args.fw.resolve(), args.out.resolve()
    if out == root or (root in out.parents and out.name != 'powerscope-identity'):
        raise ValueError('identity output must be external or FW/powerscope-identity')
    version = 'UNAVAILABLE'
    if args.cc:
        version = subprocess.check_output([str(args.cc), '--version'], text=True).strip()
        if 'arm-none-eabi' not in version.lower():
            raise ValueError('target identity requires an ARM GCC toolchain')
    inputs, files = collect(root, version)
    build_id = digest(canonical(inputs))
    out.mkdir(parents=True, exist_ok=True)
    source_zip = snapshot(files)
    (out / 'source.zip').write_bytes(source_zip)
    record = {
        'schema_version': 1, 'status': 'BUILD_PENDING', 'model': inputs['model'],
        'device_pack_version': args.device_pack_version,
        'pc_commit': git(args.pc.resolve(), 'rev-parse', 'HEAD'),
        'fw_commit': inputs['fw_commit'], 'build_id': build_id, 'build_inputs': inputs,
        'source_snapshot': {'path': 'source.zip', 'sha256': digest(source_zip)},
        'static_libraries': inputs['static_libraries'],
        'memory_regions': [
            {'name': 'Flash', 'start': 0x08000000, 'end': 0x08080000},
            {'name': 'DTCM', 'start': 0x20000000, 'end': 0x20010000},
            {'name': 'SRAM', 'start': 0x20100000, 'end': 0x20140000},
        ],
    }
    (out / 'input-record.json').write_bytes(canonical(record) + b'\n')
    header = '#ifndef POWERSCOPE_BUILD_ID_H\n#define POWERSCOPE_BUILD_ID_H\n'
    header += '#define DM_BUILD_ID_BYTES {' + ','.join(f'0x{x:02x}' for x in bytes.fromhex(build_id)) + '}\n#endif\n'
    (root / GENERATED).write_text(header, encoding='ascii')
    print(f'BUILD_PENDING build_id={build_id}; source snapshot saved')


def finalize(args):
    from elftools.elf.elffile import ELFFile
    root, out = args.fw.resolve(), args.out.resolve()
    record = json.loads((out / 'input-record.json').read_text(encoding='utf-8'))
    old_inputs = record['build_inputs']
    if old_inputs['toolchain']['version'] == 'UNAVAILABLE':
        raise ValueError('BUILD_PENDING: no target compiler was recorded')
    inputs, _ = collect(root, old_inputs['toolchain']['version'])
    if inputs != old_inputs or digest(canonical(inputs)) != record['build_id']:
        raise ValueError('build inputs changed since prepare')
    if digest((out / 'source.zip').read_bytes()) != record['source_snapshot']['sha256']:
        raise ValueError('source snapshot changed')
    with args.elf.open('rb') as stream:
        elf = ELFFile(stream)
        section = elf.get_section_by_name('.powerscope_build_id')
        if elf['e_machine'] != 'EM_ARM' or section is None or section.data() != bytes.fromhex(record['build_id']):
            raise ValueError('ELF ARM architecture or build ID section mismatch')
        # Verify the binary actually contains this linked section at its load offset.
        flash_segments = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD' and s['p_filesz'] and 0x08000000 <= s['p_paddr'] < 0x08080000]
        base = min(s['p_paddr'] for s in flash_segments)
        offset = section['sh_addr'] - base
        binary = args.bin.read_bytes()
        if offset < 0 or binary[offset:offset + 32] != section.data():
            raise ValueError('BIN does not contain the ELF build ID at its load address')
        expected = bytearray(max(s['p_paddr'] + s['p_filesz'] for s in flash_segments) - base)
        for segment in flash_segments:
            start = segment['p_paddr'] - base
            expected[start:start + segment['p_filesz']] = segment.data()
        if binary != expected:
            raise ValueError('BIN differs from ELF flash load segments')
    record['artifacts'] = {}
    for kind, path in [('elf', args.elf), ('bin', args.bin), ('map', args.map)]:
        target = out / 'artifacts' / f'firmware.{kind}'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        record['artifacts'][kind] = {'path': target.relative_to(out).as_posix(), 'sha256': digest(target.read_bytes())}
    for lib in record['static_libraries']:
        target = out / lib['path']; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / lib['path'], target)
    record['status'] = 'BUILT'
    (out / 'manifest.json').write_bytes(canonical(record) + b'\n')
    print(f'BUILT manifest={out / "manifest.json"}; BENCH_PENDING')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('prepare', 'finalize'):
        p = sub.add_parser(command)
        p.add_argument('--fw', type=Path, required=True)
        p.add_argument('--out', type=Path, required=True)
        if command == 'prepare':
            p.add_argument('--cc', type=Path)
            p.add_argument('--pc', type=Path, required=True)
            p.add_argument('--device-pack-version', default='1')
        else:
            for kind in ('elf', 'bin', 'map'):
                p.add_argument('--' + kind, type=Path, required=True)
    args = parser.parse_args()
    try:
        (prepare if args.command == 'prepare' else finalize)(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc) + '\n')

if __name__ == '__main__':
    main()
