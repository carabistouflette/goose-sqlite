#!/usr/bin/env python3
"""Record interleaved Goose/C adapter samples, checksums and provenance."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import time
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def output(*cmd):
    return subprocess.check_output(cmd, cwd=ROOT, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--goose', required=True)
    parser.add_argument('--iterations', type=int, default=10000)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 10000000 or not 1 <= args.runs <= 100:
        parser.error('iterations/runs outside supported range')
    goose = str(Path(args.goose).resolve())
    cc = os.environ.get('BENCH_CC', 'gcc')
    subprocess.run(['python3', 'scripts/native-manifest.py', '--check'], cwd=ROOT, check=True)
    build = ROOT / '.build'
    build.mkdir(exist_ok=True)
    # A fresh package cache prevents stale or ambient native build options.
    with tempfile.TemporaryDirectory(prefix='bench-cache-', dir=build) as cache:
        env = os.environ.copy()
        for key in ('CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'CMAKE_GENERATOR'):
            env.pop(key, None)
        env['GOOSE_HOME'] = cache
        subprocess.run([goose, 'build', 'bench/bench.goose', '--cc', cc, '-O2', '-o', '.build/bench-goose'], cwd=ROOT, env=env, check=True)
        archives = list(Path(cache).rglob('libgoose_sqlite_native.a'))
        if len(archives) != 1:
            raise RuntimeError('expected exactly one production native archive')
        archive = archives[0]
        caches = list(Path(cache).rglob('CMakeCache.txt'))
        if len(caches) != 1:
            raise RuntimeError('expected exactly one production CMake cache')
        values = {}
        for line in caches[0].read_text().splitlines():
            if line and not line.startswith(('#', '//')) and '=' in line and ':' in line.split('=', 1)[0]:
                key, value = line.split('=', 1)
                values[key.split(':', 1)[0]] = value
        sqlite_lib = Path(values['SQLite3_LIBRARY'])
        c_flags = ['-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread']
        subprocess.run([cc, *c_flags, '-I', values['SQLite3_INCLUDE_DIR'], 'bench/baseline.c', str(archive), str(sqlite_lib), '-o', '.build/bench-c'], cwd=ROOT, env=env, check=True)
        target_files = list(Path(cache).rglob('target-goose_sqlite_native-*.json'))
        if len(target_files) != 1:
            raise RuntimeError('expected native CMake codemodel metadata')
        native_target = json.loads(target_files[0].read_text())
        native_flags = [[f['fragment'] for f in group.get('compileCommandFragments', [])]
                        for group in native_target['compileGroups']]
        native_provenance = dict(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                                 build_type=values['CMAKE_BUILD_TYPE'], flags=native_flags,
                                 sqlite_library=sqlite_lib.name,
                                 sqlite_sha256=hashlib.sha256(sqlite_lib.read_bytes()).hexdigest(),
                                 compiler=output(values['CMAKE_C_COMPILER'], '--version').splitlines()[0])
    bins = {'goose': build / 'bench-goose', 'c-adapter': build / 'bench-c'}
    fixtures = [('prepare', 0), ('text', 0), ('text', 32), ('text', 4096), ('text', 65536), ('blob', 0), ('blob', 4096), ('blob', 1048576), ('insert', 0)]
    samples = []
    for mode, size in fixtures:
        n = max(1, args.iterations // (100 if size == 1048576 else 10)) if size >= 65536 else args.iterations
        expected = n * size if mode in ('text', 'blob') else n
        for binary in bins.values():
            subprocess.run([str(binary), '1', mode, str(size)], cwd=ROOT, check=True, capture_output=True)
        for run in range(args.runs):
            order = list(bins) if run % 2 == 0 else list(reversed(bins))
            for name in order:
                before = resource.getrusage(resource.RUSAGE_CHILDREN)
                start = time.perf_counter_ns()
                result = subprocess.run([str(bins[name]), str(n), mode, str(size)], cwd=ROOT, check=True, capture_output=True, text=True)
                wall = time.perf_counter_ns() - start
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                cpu = round(((after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)) * 1e9)
                if result.stdout.strip() != str(expected):
                    raise RuntimeError(f'bad checksum: {name} {mode} {size}: {result.stdout}')
                samples.append(dict(implementation=name, fixture=mode, bytes=size, iterations=n, run=run, wall_ns=wall, cpu_ns=cpu, checksum=expected))
    paths = [ROOT / 'CMakeLists.txt', ROOT / 'sqlite.goose', ROOT / 'GOOSE_REVISION', ROOT / 'sqlite.build']
    paths += list((ROOT / 'native').glob('*')) + [ROOT / 'bench' / p for p in ('bench.goose', 'baseline.c', 'measure.py')]
    cpuinfo = Path('/proc/cpuinfo').read_text() if Path('/proc/cpuinfo').exists() else ''
    cpu = next((line.split(':', 1)[1].strip() for line in cpuinfo.splitlines() if line.startswith('model name')), platform.processor())
    identity = output(str(bins['c-adapter']), '--identity').splitlines()
    dynamic = {name: output('ldd', str(binary)).splitlines() for name, binary in bins.items()}
    sqlite_paths = {}
    for name, lines in dynamic.items():
        sqlite_lines = [line for line in lines if 'libsqlite3' in line]
        if len(sqlite_lines) != 1:
            raise RuntimeError('expected exactly one runtime SQLite library')
        sqlite_paths[name] = Path(sqlite_lines[0].split('=>', 1)[1].split('(', 1)[0].strip()).resolve()
    runtime_hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sqlite_paths.items()}
    if len(set(runtime_hashes.values())) != 1 or next(iter(runtime_hashes.values())) != native_provenance['sqlite_sha256']:
        raise RuntimeError('SQLite runtime/build artifacts differ between callers')
    record = dict(timestamp_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  source_commit=output('git', 'rev-parse', 'HEAD'),
                  source_dirty=bool(output('git', 'status', '--porcelain')),
                  goose_revision=(ROOT / 'GOOSE_REVISION').read_text().strip(),
                  goose_binary_sha256=hashlib.sha256(Path(goose).read_bytes()).hexdigest(),
                  sqlite=identity[0], sqlite_source_id=identity[1], sqlite_compile_options=identity[2:],
                  runtime_sqlite_sha256=runtime_hashes,
                  cc=output(cc, '--version').splitlines()[0], c_flags=c_flags,
                  native=native_provenance,
                  goose_flags=['--cc', cc, '-O2'], platform=platform.platform(), cpu=cpu,
                  affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
                  sources={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                  binaries={name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in bins.items()},
                  scope='Whole-process wall and child CPU time, including startup/setup/cleanup. Same production adapter; C baseline is not unrestricted raw SQLite. Warmups excluded. Shared host, no CPU isolation.',
                  samples=samples)
    dest = args.output if args.output.is_absolute() else ROOT / args.output
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'samples.json').write_text(json.dumps(record, indent=2) + '\n')
    print(f'Recorded {len(samples)} samples in {dest / "samples.json"}')


if __name__ == '__main__':
    main()
