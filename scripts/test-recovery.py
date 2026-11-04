#!/usr/bin/env python3
"""Enumerate test-only I/O errors and process-crash recovery cutpoints."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def run(binary, directory, scenario, wal, mode, cut, sticky, expected=-1):
    cmd = [str(binary), str(directory), scenario, str(wal), mode, str(cut), str(sticky), str(expected)]
    env = os.environ.copy()
    env['UBSAN_OPTIONS'] = env.get('UBSAN_OPTIONS', '') + ':halt_on_error=1'
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=30, env=env)
    if result.stderr:
        raise RuntimeError(f'Unexpected diagnostics: {result.stderr}')
    if result.returncode not in (0, 86, 87):
        raise RuntimeError(f'{scenario}/{wal}/{mode}/{cut}/{sticky}: exit {result.returncode}\n{result.stdout}\n{result.stderr}')
    if result.returncode == 86:
        if not mode.startswith('crash-') or result.stdout != 'crash\n':
            raise RuntimeError('Unexpected crash/acknowledgement')
        return {'crashed': True, 'acknowledged': False}
    if result.returncode == 87:
        if mode != 'crash-after-ack' or result.stdout != 'ack\n':
            raise RuntimeError('Invalid acknowledged crash')
        return {'crashed': True, 'acknowledged': True}
    lines = result.stdout.splitlines()
    acknowledged = bool(lines and lines[0] == 'ack')
    record = json.loads(lines[-1])
    if mode.startswith('crash-') and not record.get('skipped') and not acknowledged:
        raise RuntimeError('Successful crash-control operation lacked acknowledgement')
    return dict(record, crashed=False, acknowledged=acknowledged)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--require-wal', action='store_true', help='Fail if any WAL group is skipped')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve(); args.output.parent.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parent.parent
    paths = ('native/sqlite.c', 'native/sqlite.h', 'CMakeLists.txt', 'tests/recovery.c', 'scripts/test-recovery.py')
    provenance = dict(source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
                      source_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip()),
                      source_hashes={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    added_modes = ('read', 'truncate', 'delete', 'shm-map', 'shm-lock')
    records = []; modes = [('write', 0), ('write', 1), ('full', 0), ('full', 1),
                           ('sync', 0), ('sync', 1), ('crash-write', 0), ('crash-sync', 0)]
    modes += [(mode, sticky) for mode in added_modes for sticky in (0, 1)]
    journal = args.output.with_suffix('.jsonl'); journal.write_text('')
    for scenario in ('commit', 'blob', 'backup', 'checkpoint'):
        for wal in ((1,) if scenario == 'checkpoint' else (0, 1)):
            for mode, sticky in modes:
                reached = 0
                for cut in range(1, 10001):
                    with tempfile.TemporaryDirectory(prefix='goose-recovery-') as directory:
                        record = run(binary, directory, scenario, wal, mode, cut, sticky)
                        if record.get('crashed'):
                            recovered = run(binary, directory, scenario, wal, 'verify', 0, 0, 1 if scenario == 'checkpoint' else -1)
                            record['epoch'] = recovered['epoch']
                            if scenario == 'checkpoint': record['recovery'] = recovered
                        record.update(scenario=scenario, wal=bool(wal), mode=mode, sticky=bool(sticky), cut=cut)
                    if not record.get('skipped') and not record.get('crashed') and not record.get('fired'):
                        record['unexercised'] = reached == 0
                    records.append(record)
                    with journal.open('a') as stream: stream.write(json.dumps(record) + '\n')
                    if record.get('skipped'):
                        if args.require_wal: raise RuntimeError('Required positive WAL coverage was skipped')
                        break
                    if record.get('crashed') or record['fired']:
                        reached += 1
                    else:
                        required = mode not in added_modes or (scenario == 'checkpoint' and mode in ('truncate', 'shm-lock'))
                        if record['code'] != 0 or record['epoch'] != 1 or (reached == 0 and required):
                            raise RuntimeError('Missing successful terminal trial or fault coverage')
                        break
                else:
                    raise RuntimeError('Fault enumeration exceeded defensive cap')
            with tempfile.TemporaryDirectory(prefix='goose-recovery-') as directory:
                control = run(binary, directory, scenario, wal, 'crash-after-ack', 0, 0)
                if control.get('skipped') and args.require_wal:
                    raise RuntimeError('Required acknowledged WAL coverage was skipped')
                if not control.get('skipped'):
                    if not control['crashed'] or not control['acknowledged']:
                        raise RuntimeError('Missing crash after success acknowledgement')
                    recovered = run(binary, directory, scenario, wal, 'verify', 0, 0, 1)
                    control['epoch'] = recovered['epoch']
                    if scenario == 'checkpoint': control['recovery'] = recovered
                control.update(scenario=scenario, wal=bool(wal), mode='crash-after-ack', sticky=False, cut=0)
            records.append(control)
            with journal.open('a') as stream: stream.write(json.dumps(control) + '\n')
    if not any(r.get('fault_phase') == 2 and r.get('fired') for r in records if r['scenario'] == 'blob'):
        raise RuntimeError('No failures reached incremental blob_write')
    legacy_records = [r for r in records if r['scenario'] != 'checkpoint']
    wal_supported = any(r['wal'] and not r.get('skipped') for r in legacy_records)
    for mode in added_modes:
        if mode.startswith('shm-') and not wal_supported:
            continue
        for sticky in (False, True):
            if not any(r['mode'] == mode and r['sticky'] == sticky and r.get('fired') for r in legacy_records):
                raise RuntimeError(f'No actual fault coverage for {mode}, sticky={sticky}')
    for r in records:
        if r['scenario'] == 'checkpoint' and not r.get('skipped'):
            if r.get('epoch') != 1 or not (r.get('checkpoint_retry') or r.get('recovery', {}).get('checkpoint_retry')):
                raise RuntimeError('Checkpoint lost previously committed data or lacked verified retry')
    links = subprocess.check_output(['ldd', str(binary)], text=True).splitlines()
    engine_paths = [Path(line.split('=>', 1)[1].split('(', 1)[0].strip()).resolve()
                    for line in links if 'libsqlite3' in line and '=>' in line]
    if len(engine_paths) != 1: raise RuntimeError('Expected one shared SQLite engine')
    flags = binary.parent / 'CMakeFiles/goose_sqlite_recovery_test.dir/flags.make'
    coverage = {mode: dict(trials=sum(r['mode'] == mode for r in records),
                           hit_trials=sum(r['mode'] == mode and bool(r.get('fired') or r.get('crashed')) for r in records),
                           unexercised_groups=sum(r['mode'] == mode and r.get('unexercised', False) for r in records),
                           skipped_groups=sum(r['mode'] == mode and r.get('skipped', False) for r in records))
                for mode in dict.fromkeys(r['mode'] for r in records)}
    record = dict(provenance=provenance, coverage=coverage, test_compile_flags=[line for line in flags.read_text().splitlines() if line.startswith('C_FLAGS =')] if flags.exists() else [],
                  compile_flags_note='CMake flags.make when available; empty for other generators',
                  sqlite_library=dict(file=engine_paths[0].name, sha256=hashlib.sha256(engine_paths[0].read_bytes()).hexdigest()), sqlite_identity=json.loads(subprocess.check_output([str(binary), 'identity'], text=True)), binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                  scope='Single-threaded test-only VFS; failures before complete read/write/sync/truncate/delete/SHM-map/SHM-lock-acquisition calls; mmap disabled. Process crashes preserve OS cache; no torn-write/power-loss/reordering model. Fresh fixtures per cutpoint; all bytes and integrity checked. WAL-only checkpoint faults start after epoch1 commit and always require epoch1 plus a verified successful checkpoint retry before any write.',
                  records=records)
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    hits = sum(bool(r.get('fired') or r.get('crashed')) for r in records)
    skips = sum(bool(r.get('skipped')) for r in records)
    print(f'Recovery passed: {len(records)} trials, {hits} fault/crash points, {skips} unsupported WAL groups')


if __name__ == '__main__':
    main()
