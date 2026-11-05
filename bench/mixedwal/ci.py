#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run positive WAL smoke on a separately verified, non-sanitized pinned engine."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bench/alternatives'))
from paired import run  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--goose', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--engine-output', type=Path, default=Path('.build/mixedwal-ci-engine'))
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('verified_engine', ROOT / 'scripts/test-wal-engine.py')
    pinned = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pinned)
    source = ROOT / '.build/wal-engine/sqlite3.c'
    source_bytes = source.read_bytes()
    if hashlib.sha3_256(source_bytes).hexdigest() != pinned.SOURCE_SHA3:
        raise RuntimeError('Run the maintained pinned-engine validation first; source hash must match')
    directory = args.engine_output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    frozen_source = directory / 'sqlite3.c'
    frozen_source.write_bytes(source_bytes)
    library = directory / 'libsqlite3.so.0'
    compiler = Path(shutil.which('gcc')).resolve(strict=True)
    flags = ['-O2', '-std=c11', '-shared', '-fPIC', '-DSQLITE_THREADSAFE=1',
             '-DSQLITE_DEFAULT_WAL_SYNCHRONOUS=2', '-DSQLITE_ENABLE_COLUMN_METADATA', '-Wl,-soname,libsqlite3.so.0']
    env = os.environ.copy()
    for name in ('LD_PRELOAD', 'LD_AUDIT', 'LD_LIBRARY_PATH', 'CFLAGS', 'CPPFLAGS', 'LDFLAGS'):
        env.pop(name, None)
    compiler_sha256 = hashlib.sha256(compiler.read_bytes()).hexdigest()
    run([compiler, *flags, frozen_source, '-ldl', '-pthread', '-o', library], env=env, timeout=300)
    if hashlib.sha256(compiler.read_bytes()).hexdigest() != compiler_sha256:
        raise RuntimeError('CI engine compiler changed during build')
    if hashlib.sha3_256(frozen_source.read_bytes()).hexdigest() != pinned.SOURCE_SHA3:
        raise RuntimeError('Frozen CI engine source changed during compilation')
    # Both Linux SONAME conventions resolve to the same explicitly recorded object.
    (directory / 'libsqlite3.so.3').symlink_to(library.name)
    (directory / 'libsqlite3.so').symlink_to(library.name)
    evidence = dict(upstream_url=pinned.URL, upstream_archive_sha256=pinned.ARCHIVE_SHA256,
                    sqlite_source_sha3_256=pinned.SOURCE_SHA3, compiler=compiler.name,
                    compiler_sha256=compiler_sha256,
                    compiler_version=run([compiler, '--version'], env=env, timeout=30)[0].splitlines()[0],
                    flags=flags, engine_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
                    scope='Test-only regular engine for positive mixed-WAL correctness smoke, not production or timing data.')
    (directory / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    env['LD_LIBRARY_PATH'] = str(directory)
    command = [sys.executable, str(ROOT / 'bench/mixedwal/measure.py'),
                    '--goose', str(Path(args.goose).resolve()), '--engine-dir', str(directory),
                    '--attempts', '8', '--rows', '4', '--rounds', '2', '--read-cap', '20000',
                    '--smoke', '--output', str(args.output.resolve())]
    # Replace this wrapper so the bounded orchestrator owns actor lifetimes.
    os.execve(sys.executable, command, env)


if __name__ == '__main__':
    main()
