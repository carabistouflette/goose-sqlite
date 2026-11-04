#!/usr/bin/env python3
"""Measure owned whole-column copies versus incremental SQLite BLOB ranges."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import resource
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def output(cmd, **kwargs):
    return subprocess.check_output([str(x) for x in cmd], cwd=ROOT, text=True, **kwargs).strip()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def engine(path):
    hits = [line for line in output(['ldd', path]).splitlines() if 'libsqlite3' in line and '=>' in line]
    if len(hits) != 1: raise RuntimeError('Expected exactly one shared SQLite engine')
    path = Path(hits[0].split('=>', 1)[1].split('(', 1)[0].strip()).resolve()
    return dict(file=path.name, sha256=digest(path))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--goose', required=True)
    ap.add_argument('--iterations', type=int, default=20000)
    ap.add_argument('--runs', type=int, default=9)
    ap.add_argument('--cpu', type=int)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if not 1 <= args.iterations <= 10000000 or not 1 <= args.runs <= 100: ap.error('Invalid iterations/runs')
    if args.cpu is not None: os.sched_setaffinity(0, {args.cpu})
    dest = args.output.resolve(); dest.mkdir(parents=True, exist_ok=True)
    build = ROOT / '.build/storage-bench'; build.mkdir(parents=True, exist_ok=True)
    goose = Path(args.goose).resolve()
    env = os.environ.copy()
    for key in ('CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'CMAKE_GENERATOR', 'CMAKE_TOOLCHAIN_FILE'):
        env.pop(key, None)
    output(['python3', 'scripts/native-manifest.py', '--check'])
    with tempfile.TemporaryDirectory(prefix='storage-cache-', dir=build) as cache:
        env['GOOSE_HOME'] = cache
        subprocess.run([str(goose), 'build', 'bench/storage/runner.goose', '--cc', 'gcc', '-O2', '-o', str(build / 'goose')], cwd=ROOT, env=env, check=True)
        caches = list(Path(cache).rglob('CMakeCache.txt'))
        if len(caches) != 1: raise RuntimeError('Expected one native CMake cache')
        values = {}
        for line in caches[0].read_text().splitlines():
            if line and not line.startswith(('#', '//')) and '=' in line and ':' in line.split('=', 1)[0]:
                key, value = line.split('=', 1); values[key.split(':', 1)[0]] = value
        target_files = list(Path(cache).rglob('target-goose_sqlite_native-*.json'))
        if len(target_files) != 1: raise RuntimeError('Expected native target codemodel')
        target = json.loads(target_files[0].read_text())
        native = dict(compiler=Path(values['CMAKE_C_COMPILER']).name, compiler_version=output([values['CMAKE_C_COMPILER'], '--version']).splitlines()[0], compiler_sha256=digest(Path(values['CMAKE_C_COMPILER']).resolve()), build_type=values['CMAKE_BUILD_TYPE'], flags=[[f['fragment'] for f in group.get('compileCommandFragments', [])] for group in target['compileGroups']],
                      archive_sha256=digest(next(Path(cache).rglob('libgoose_sqlite_native.a'))))
        subprocess.run(['gcc', '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', values['SQLite3_INCLUDE_DIR'], 'bench/storage/raw.c', values['SQLite3_LIBRARY'], '-o', str(build / 'raw')], cwd=ROOT, env=env, check=True)
    bins = {'goose': build / 'goose', 'sqlite-c-api': build / 'raw'}
    libraries = {name: engine(path) for name, path in bins.items()}
    if len({value['sha256'] for value in libraries.values()}) != 1: raise RuntimeError('Different SQLite engines')
    sources = ['sqlite.goose', 'sqlite.build', 'native/sqlite.c', 'native/sqlite.h', 'CMakeLists.txt', 'GOOSE_REVISION']
    sources += [str(path.relative_to(ROOT)) for path in (ROOT / 'bench/storage').glob('*') if path.is_file()]
    metadata = dict(timestamp_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), source_commit=output(['git', 'rev-parse', 'HEAD']),
                    source_dirty=bool(output(['git', 'status', '--porcelain'])), source_hashes={p: digest(ROOT / p) for p in sources},
                    goose_revision=(ROOT / 'GOOSE_REVISION').read_text().strip(), goose_sha256=digest(goose),
                    toolchains={tool: output([tool, '--version']).splitlines()[0] for tool in ('gcc','cmake')},
                    compiler_flags={'Goose': '--cc gcc -O2', 'raw C': '-O2 -std=c11 -Wall -Wextra -Werror; always-on CHECK'}, native_build=native,
                    sqlite_identity=output([bins['sqlite-c-api'], 'identity']).splitlines(), sqlite_libraries=libraries,
                    binary_sha256={name: digest(path) for name, path in bins.items()}, os=platform.platform(),
                    cpu_model=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), ''),
                    affinity=sorted(os.sched_getaffinity(0)), load_start=os.getloadavg(), order_seed=219,
                    scope='Shared nonexclusive CPU. In-memory 512KiB stored BLOB, read transaction, deterministic offsets. Reused output. Full fixture verified in both APIs before timing. Timed byte comparison of requested range. Lifecycle excluded. Goose retains safety policy; raw C defaults with NOMUTEX/private cache. No disk, heap or RSS conclusion.')
    journal = dest / 'samples.jsonl'; journal.write_text('')
    samples = []; rng = random.Random(219)
    for count in (64, 4096, 65536, 524288):
        cases = [(name, mode) for name in bins for mode in ('whole','incremental')]
        for name, mode in cases: output([bins[name], '10', mode, count])
        for repeat in range(args.runs):
            rng.shuffle(cases)
            for position, (name, mode) in enumerate(cases):
                before = resource.getrusage(resource.RUSAGE_CHILDREN); start = time.perf_counter_ns()
                raw = output([bins[name], args.iterations, mode, count])
                wall = time.perf_counter_ns() - start; after = resource.getrusage(resource.RUSAGE_CHILDREN)
                elapsed, checksum = map(int, raw.split())
                if elapsed <= 0 or checksum != args.iterations * count: raise RuntimeError(f'Invalid output: {raw}')
                sample = dict(implementation=name, mode=mode, stored_bytes=524288, range_bytes=count,
                              iterations=args.iterations, run=repeat, order=position, loop_wall_ns=elapsed,
                              checksum=checksum, raw_stdout=raw, whole_wall_ns=wall,
                              whole_cpu_ns=round((after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)*1e9))
                samples.append(sample)
                with journal.open('a') as stream: stream.write(json.dumps(sample)+'\n')
    metadata.update(load_end=os.getloadavg(), samples=samples)
    (dest / 'samples.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(f'{len(samples)} checked samples: {dest / "samples.json"}')


if __name__ == '__main__':
    main()
