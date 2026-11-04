#!/usr/bin/env python3
"""Build pinned alternatives and record checked, in-process API-path timings."""
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
import sys
import time
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CPP_REV = 'df0a28ca9733f687ab7ce77f070c0df84368a45e'


def run(cmd, **kwargs):
    return subprocess.run([str(x) for x in cmd], cwd=ROOT, check=True, **kwargs)


def output(cmd):
    return run(cmd, text=True, stdout=subprocess.PIPE).stdout.strip()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def engine(path):
    lines = output(['ldd', path]).splitlines()
    hits = [line for line in lines if 'libsqlite3' in line and '=>' in line]
    if len(hits) != 1:
        raise RuntimeError(f'Cannot prove one shared SQLite engine: {path}')
    lib = Path(hits[0].split('=>', 1)[1].split('(', 1)[0].strip()).resolve()
    return {'file': lib.name, 'sha256': digest(lib)}


def measured(cmd, directory):
    # GNU time execs first, then starts the benchmark from its small native image.
    # Direct wait4 ru_maxrss can retain the Python parent's pre-exec memory floor.
    with tempfile.TemporaryDirectory(prefix='rss-', dir=directory) as tmp:
        rss = Path(tmp) / 'rss.txt'
        result = run(['/usr/bin/time', '-o', rss, '-f', '%M', '--', *cmd], text=True, stdout=subprocess.PIPE)
        peak = int(rss.read_text().strip())
        if peak < 0: raise RuntimeError('Invalid GNU time RSS')
        return result.stdout.strip(), peak


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--goose', required=True)
    ap.add_argument('--iterations', type=int, default=100000)
    ap.add_argument('--runs', type=int, default=7)
    ap.add_argument('--cpu', type=int)
    ap.add_argument('--output', type=Path, default=Path('.build/alternative-results'))
    args = ap.parse_args()
    if not 1 <= args.iterations <= 10000000 or not 1 <= args.runs <= 100:
        ap.error('iterations/runs outside range')
    if args.cpu is not None: os.sched_setaffinity(0, {args.cpu})
    paths = [p for p in (ROOT / 'bench/alternatives').rglob('*') if p.is_file() and 'target' not in p.parts and '__pycache__' not in p.parts]
    paths += [ROOT / p for p in ('sqlite.goose', 'sqlite.build', 'CMakeLists.txt', 'native/sqlite.c', 'native/sqlite.h', 'GOOSE_REVISION')]
    parent_started_utc = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    source_commit = output(['git', 'rev-parse', 'HEAD'])
    source_dirty = bool(output(['git', 'status', '--porcelain']))
    source_hashes = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    env = os.environ.copy()
    for key in list(env):
        if key in ('CFLAGS','CXXFLAGS','CPPFLAGS','LDFLAGS','CMAKE_GENERATOR','CMAKE_TOOLCHAIN_FILE','CARGO_BUILD_TARGET','CARGO_TARGET_DIR','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS') or key.startswith('CARGO_PROFILE_RELEASE_'):
            env.pop(key, None)
    env['CARGO_ENCODED_RUSTFLAGS'] = ''
    env['CARGO_INCREMENTAL'] = '1'
    env['RUSTC_WRAPPER'] = ''
    env['RUSTC_WORKSPACE_WRAPPER'] = ''
    rustc = Path(output(['rustc','--print','sysroot'])) / 'bin/rustc'
    env['RUSTC'] = str(rustc)
    rustc_identity = dict(version=output([rustc,'--version']), sha256=digest(rustc))
    build = ROOT / '.build' / 'alternatives'
    build.mkdir(parents=True, exist_ok=True)
    cpp = build / 'SQLiteCpp'
    if not (cpp / '.git').exists():
        run(['git', 'clone', 'https://github.com/SRombauts/SQLiteCpp.git', cpp])
    run(['git', '-C', cpp, 'fetch', '--depth', '1', 'origin', CPP_REV])
    run(['git', '-C', cpp, 'checkout', '--detach', CPP_REV])
    if output(['git','-C',cpp,'rev-parse','HEAD']) != CPP_REV or output(['git','-C',cpp,'status','--porcelain','--untracked-files=all']):
        raise RuntimeError('Expected a clean pinned SQLiteCpp checkout')
    run(['cmake', '--fresh', '-S', cpp, '-B', build / 'cpp-build', '-DSQLITECPP_INTERNAL_SQLITE=OFF',
         '-DSQLITECPP_BUILD_TESTS=OFF', '-DSQLITECPP_BUILD_EXAMPLES=OFF', '-DCMAKE_BUILD_TYPE=Release',
         '-DCMAKE_CXX_FLAGS_RELEASE=-O2 -DNDEBUG', '-DCMAKE_CXX_FLAGS=', '-DCMAKE_CXX_COMPILER=g++', '-DCMAKE_C_COMPILER=gcc', '-DCMAKE_CXX_COMPILER_LAUNCHER=', '-DCMAKE_C_COMPILER_LAUNCHER='], env=env)
    run(['cmake', '--build', build / 'cpp-build', '--parallel', '2'])
    cpp_values = {}
    for line in (build / 'cpp-build/CMakeCache.txt').read_text().splitlines():
        if line and not line.startswith(('#','//')) and '=' in line and ':' in line.split('=',1)[0]:
            key, value = line.split('=',1); cpp_values[key.split(':',1)[0]] = value
    if cpp_values.get('CMAKE_BUILD_TYPE') != 'Release' or cpp_values.get('SQLITECPP_INTERNAL_SQLITE') != 'OFF' or cpp_values.get('CMAKE_CXX_FLAGS_RELEASE') != '-O2 -DNDEBUG':
        raise RuntimeError('Unexpected SQLiteCpp engine/profile configuration')
    cpp_build = dict(build_type=cpp_values['CMAKE_BUILD_TYPE'], compiler=output([cpp_values['CMAKE_CXX_COMPILER'],'--version']).splitlines()[0],
                     release_flags=cpp_values['CMAKE_CXX_FLAGS_RELEASE'], internal_sqlite=cpp_values['SQLITECPP_INTERNAL_SQLITE'],
                     archive_sha256=digest(build / 'cpp-build/libSQLiteCpp.a'))

    cpp_include = '-I' + str(cpp / 'include')
    for name, flags in [('raw-c-api', []), ('sqlitecpp', ['-DUSE_SQLITECPP', cpp_include])]:
        cmd = ['g++', '-std=c++17', '-O2', *flags, 'bench/alternatives/native.cpp']
        if name == 'sqlitecpp': cmd += [build / 'cpp-build' / 'libSQLiteCpp.a']
        run([*cmd, '-lsqlite3', '-o', build / name])
    host = next(line.split(': ',1)[1] for line in output([rustc,'-vV']).splitlines() if line.startswith('host: '))
    run(['cargo', 'build', '--locked', '--release', '--target', host, '--target-dir', build / 'rust-target', '--manifest-path', 'bench/alternatives/rust/Cargo.toml', '--config', 'profile.release.opt-level=2', '--config', 'profile.release.lto="thin"', '--config', 'profile.release.codegen-units=16', '--config', 'profile.release.incremental=true'], env=env)
    goose = str(Path(args.goose).resolve())
    env['GOOSE_HOME'] = str(build / ('goose-cache-' + str(time.monotonic_ns())))
    run(['python3', 'scripts/native-manifest.py', '--check'])
    run([goose, 'build', 'bench/alternatives/runner.goose', '--cc', 'gcc', '-O2', '-o', build / 'goose'], env=env)
    native_caches = list(Path(env['GOOSE_HOME']).rglob('CMakeCache.txt'))
    if len(native_caches) != 1: raise RuntimeError('Expected one production native cache')
    native_values = {}
    for line in native_caches[0].read_text().splitlines():
        if line and not line.startswith(('#','//')) and '=' in line and ':' in line.split('=',1)[0]:
            key, value = line.split('=',1); native_values[key.split(':',1)[0]] = value
    targets = list(Path(env['GOOSE_HOME']).rglob('target-goose_sqlite_native-*.json'))
    if len(targets) != 1: raise RuntimeError('Expected native build codemodel')
    target = json.loads(targets[0].read_text())
    native_build = dict(build_type=native_values['CMAKE_BUILD_TYPE'], compiler=output([native_values['CMAKE_C_COMPILER'],'--version']).splitlines()[0],
                        flags=[[f['fragment'] for f in group.get('compileCommandFragments',[])] for group in target['compileGroups']],
                        archive_sha256=digest(next(Path(env['GOOSE_HOME']).rglob('libgoose_sqlite_native.a'))))
    rust = build / 'rust-target' / host / 'release/sqlite-alternative-bench'
    runners = {'goose': [str(build / 'goose')], 'raw-c-api': [str(build / 'raw-c-api')],
               'sqlitecpp': [str(build / 'sqlitecpp')], 'rusqlite': [str(rust)],
               'python': [sys.executable, '-I', str(ROOT / 'bench/alternatives/python.py')]}
    identities = {name: output([*cmd, 'identity']).splitlines() for name, cmd in runners.items() if name != 'goose'}
    if len({tuple(v) for v in identities.values()}) != 1:
        raise RuntimeError('SQLite runtime versions/source IDs/compile options differ')
    import _sqlite3
    libraries = {name: engine(cmd[0]) for name, cmd in runners.items() if name != 'python'}
    libraries['python'] = engine(_sqlite3.__file__)
    if len({v['sha256'] for v in libraries.values()}) != 1:
        raise RuntimeError('SQLite shared-library hashes differ')
    import sqlite3
    plans_db = sqlite3.connect(':memory:')
    plans_db.executescript('CREATE TABLE items(id INTEGER PRIMARY KEY,group_id INTEGER,payload BLOB); CREATE INDEX by_group ON items(group_id);')
    query_plans = {name: plans_db.execute('EXPLAIN QUERY PLAN ' + sql, params).fetchall()
                   for name,sql,params in [('scan','SELECT id,payload FROM items ORDER BY id',()),
                                           ('lookup','SELECT id,payload FROM items WHERE id=?1',(17,))]}
    plans_db.close()
    if not any('INTEGER PRIMARY KEY' in row[3] for row in query_plans['lookup']):
        raise RuntimeError('Lookup is not using the intended primary-key plan')
    fixtures = [('prepare', 0), ('scalar', 0), ('text', 32), ('text', 4096), ('text', 65536), ('blob', 4096), ('insert', 0), ('scan', 128), ('lookup', 128), ('batch', 128)]
    samples = []
    dest = args.output if args.output.is_absolute() else ROOT / args.output
    dest.mkdir(parents=True, exist_ok=True)
    journal = dest / 'samples.jsonl'
    journal.write_text('')
    failure = dest / 'failure.json'
    if failure.exists(): failure.unlink()
    rng = random.Random(219)
    for mode, size in fixtures:
        n = max(1, args.iterations // 1024) if mode == 'scan' else max(1, args.iterations // 10) if size >= 65536 else args.iterations
        operations = n * 1024 if mode == 'scan' else n
        expected = n * (n - 1) // 2 if mode == 'scalar' else operations * size if mode in ('text', 'blob', 'scan', 'lookup', 'batch') else n
        for name, cmd in runners.items():
            output([*cmd, '1' if mode == 'scan' else '10', mode, str(size)])
        for repeat in range(args.runs):
            order = list(runners)
            rng.shuffle(order)
            for position, name in enumerate(order):
                before = resource.getrusage(resource.RUSAGE_CHILDREN)
                whole_start_utc_ns = time.time_ns()
                start = time.perf_counter_ns()
                try:
                    text, peak_rss_kib = measured([*runners[name], str(n), mode, str(size)], build)
                except subprocess.CalledProcessError as error:
                    failure.write_text(json.dumps(dict(implementation=name, fixture=mode, bytes=size,
                                                      iterations=n, run=repeat, returncode=error.returncode)) + '\n')
                    raise
                whole = time.perf_counter_ns() - start
                whole_end_utc_ns = time.time_ns()
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                elapsed, checksum = map(int, text.split())
                if elapsed <= 0 or checksum != expected: raise RuntimeError(f'Bad result: {name}: {text}')
                samples.append(dict(implementation=name, fixture=mode, bytes=size, iterations=n, operations=operations, peak_rss_kib=peak_rss_kib,
                                    run=repeat, order=position, loop_wall_ns=elapsed, checksum=checksum,
                                    whole_wall_ns=whole, whole_start_utc_ns=whole_start_utc_ns, whole_end_utc_ns=whole_end_utc_ns, whole_cpu_ns=round((after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) * 1e9)))
                with journal.open('a') as stream:
                    stream.write(json.dumps(samples[-1]) + '\n')
    if output(['git','rev-parse','HEAD']) != source_commit or any(digest(ROOT / p) != h for p,h in source_hashes.items()):
        raise RuntimeError('Measured source changed during the series')
    if output(['git','-C',cpp,'rev-parse','HEAD']) != CPP_REV or output(['git','-C',cpp,'status','--porcelain','--untracked-files=all']):
        raise RuntimeError('SQLiteCpp checkout changed during the series')
    if {name: engine(cmd[0]) for name,cmd in runners.items() if name != 'python'} != {name: lib for name,lib in libraries.items() if name != 'python'} or engine(_sqlite3.__file__) != libraries['python']:
        raise RuntimeError('SQLite engine changed during the series')

    metadata = dict(parent_started_utc=parent_started_utc, timestamp_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), source_commit=source_commit, source_dirty=source_dirty,
                    goose_revision=(ROOT / 'GOOSE_REVISION').read_text().strip(), goose_sha256=digest(goose),
                    wrapper_versions={'SQLiteCpp': {'version': '3.4.0', 'revision': CPP_REV}, 'rusqlite': '0.41.1', 'Python': sys.version},
                    rss_measurement=dict(tool='GNU time %M, benchmark-child whole-lifetime peak KiB on Linux; includes startup/setup/verification and small native pre-exec launch overhead; no Python-parent RSS floor, no incremental-heap claim', version=output(['/usr/bin/time','--version']).splitlines()[0], sha256=digest('/usr/bin/time')),
                    toolchains={tool: output([str(rustc) if tool == 'rustc' else tool, '--version']).splitlines()[0] for tool in ('gcc', 'g++', 'rustc', 'cargo', 'cmake')},
                    native_build=native_build, sqlitecpp_build=cpp_build, rustc_identity=rustc_identity,
                    compiler_flags={'C++ caller': '-O2 -std=c++17, always-on checks', 'SQLiteCpp': '-O2 -DNDEBUG', 'Rust': 'opt-level=2,lto=thin,codegen-units=16,incremental=true,normal assertions active,compiler wrappers disabled', 'Goose': '--cc gcc -O2; native CMake Release'},
                    sqlite_identities=identities, sqlite_libraries=libraries, query_plans=query_plans,
                    binaries={name: digest(cmd[0]) for name, cmd in runners.items()},
                    source_hashes=source_hashes,
                    os=platform.platform(), cpu_model=next((v.split(':',1)[1].strip() for v in Path('/proc/cpuinfo').read_text().splitlines() if v.startswith('model name')), ''),
                    affinity=sorted(os.sched_getaffinity(0)), order_seed=219,
                    scope='Goose work_budget=100000000 permits untimed aggregate verification; other hardening retained. In-process checked API paths, not policy-equivalent or universal rankings. Goose retains fixed security/resource policy; other callers use documented defaults. Whole-process wall/CPU times include GNU time launcher overhead; loop clocks exclude it. Whole-lifetime child RSS may peak during setup or verification. New row fixtures reuse owned outputs in Goose/C/C++/Rust; Python returns fresh immutable bytes. Shared host.', samples=samples)
    dest = args.output if args.output.is_absolute() else ROOT / args.output
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'samples.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'Recorded {len(samples)} checked samples in {dest / "samples.json"}')


if __name__ == '__main__': main()
