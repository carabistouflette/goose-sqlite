#!/usr/bin/env python3
"""Run bounded concurrent adapter checks and retain source/engine provenance."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-wal', action='store_true')
    parser.add_argument('--initialize-engine', action='store_true',
                        help='Initialize SQLite serially before racing first wrapper use')
    args = parser.parse_args()
    binary = args.binary.resolve()
    env = os.environ.copy()
    env['UBSAN_OPTIONS'] = 'halt_on_error=1'
    # A race or sanitizer startup failure must fail; never retry to hide it.
    env['TSAN_OPTIONS'] = 'halt_on_error=1:exitcode=66'
    cmd = [str(binary)] + (['--initialize-engine'] if args.initialize_engine else [])
    result = subprocess.run(cmd, env=env, text=True, capture_output=True, timeout=180)
    if result.returncode or result.stderr:
        raise RuntimeError(f'Thread stress failed ({result.returncode}):\n{result.stdout}\n{result.stderr}')
    counters = json.loads(result.stdout)
    if counters['engine_preinitialized'] != args.initialize_engine:
        raise RuntimeError('Incorrect engine initialization mode')
    for key, expected in dict(threads=8, waves=8, registry_cycles=1024,
                              unique_tokens=3072, cleanup_callbacks=64).items():
        if counters[key] != expected:
            raise RuntimeError(f'Missing thread coverage: {key}')
    if args.require_wal and not counters['wal']:
        raise RuntimeError('Required positive WAL concurrency coverage was skipped')
    if counters['wal'] and (counters['committed'] != 256 or counters['reader_snapshots'] < 160):
        raise RuntimeError('Missing WAL concurrency coverage')
    links = subprocess.check_output(['ldd', str(binary)], text=True).splitlines()
    engines = [Path(line.split('=>', 1)[1].split('(', 1)[0].strip()).resolve()
               for line in links if 'libsqlite3' in line and '=>' in line]
    if len(engines) != 1:
        raise RuntimeError('Expected one shared SQLite engine')
    paths = ('native/sqlite.c', 'native/sqlite.h', 'CMakeLists.txt',
             'tests/threads.c', 'scripts/test-threads.py')
    def compile_flags(target):
        flags = binary.parent / f'CMakeFiles/{target}.dir/flags.make'
        return [line for line in flags.read_text().splitlines() if line.startswith('C_FLAGS =')] if flags.exists() else []
    record = dict(source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  source_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
                  source_hashes={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths},
                  architecture=platform.machine(), counters=counters,
                  engine_initialization='serial' if args.initialize_engine else 'concurrent cold start',
                  test_compile_flags=compile_flags('goose_sqlite_thread_test'),
                  adapter_compile_flags=compile_flags('goose_sqlite_native'),
                  compile_flags_note='CMake C_FLAGS when available; empty for other generators',
                  binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                  sqlite_library_sha256=hashlib.sha256(engines[0].read_bytes()).hexdigest(),
                  sqlite_identity=json.loads(subprocess.check_output([str(binary), 'identity'], env=env, text=True)),
                  scope='Finite correctness stress; independent thread-affine connections, not shared-handle support or a performance benchmark')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(counters, sort_keys=True))


if __name__ == '__main__':
    main()
