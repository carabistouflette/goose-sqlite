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
    env = os.environ.copy()
    for key in list(env):
        if key in ('CFLAGS','CXXFLAGS','CPPFLAGS','LDFLAGS','CMAKE_GENERATOR','CMAKE_TOOLCHAIN_FILE','CARGO_BUILD_TARGET','CARGO_TARGET_DIR','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS') or key.startswith('CARGO_PROFILE_RELEASE_'):
            env.pop(key, None)
    env['CARGO_ENCODED_RUSTFLAGS'] = ''
    build = ROOT / '.build' / 'alternatives'
    build.mkdir(parents=True, exist_ok=True)
    cpp = build / 'SQLiteCpp'
    if not (cpp / '.git').exists():
        run(['git', 'clone', 'https://github.com/SRombauts/SQLiteCpp.git', cpp])
    run(['git', '-C', cpp, 'fetch', '--depth', '1', 'origin', CPP_REV])
    run(['git', '-C', cpp, 'checkout', '--detach', CPP_REV])
    run(['cmake', '-S', cpp, '-B', build / 'cpp-build', '-DSQLITECPP_INTERNAL_SQLITE=OFF',
         '-DSQLITECPP_BUILD_TESTS=OFF', '-DSQLITECPP_BUILD_EXAMPLES=OFF', '-DCMAKE_BUILD_TYPE=Release',
         '-DCMAKE_CXX_FLAGS_RELEASE=-O2 -DNDEBUG', '-DCMAKE_CXX_FLAGS='], env=env)
    run(['cmake', '--build', build / 'cpp-build', '--parallel', '2'])
    cpp_include = '-I' + str(cpp / 'include')
    for name, flags in [('raw-c-api', []), ('sqlitecpp', ['-DUSE_SQLITECPP', cpp_include])]:
        cmd = ['g++', '-std=c++17', '-O2', *flags, 'bench/alternatives/native.cpp']
        if name == 'sqlitecpp': cmd += [build / 'cpp-build' / 'libSQLiteCpp.a']
        run([*cmd, '-lsqlite3', '-o', build / name])
    host = next(line.split(': ',1)[1] for line in output(['rustc','-vV']).splitlines() if line.startswith('host: '))
    run(['cargo', 'build', '--locked', '--release', '--target', host, '--target-dir', build / 'rust-target', '--manifest-path', 'bench/alternatives/rust/Cargo.toml'], env=env)
    goose = str(Path(args.goose).resolve())
    env['GOOSE_HOME'] = str(build / ('goose-cache-' + str(time.monotonic_ns())))
    run(['python3', 'scripts/native-manifest.py', '--check'])
    run([goose, 'build', 'bench/alternatives/runner.goose', '--cc', 'gcc', '-O2', '-o', build / 'goose'], env=env)
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
    fixtures = [('prepare', 0), ('scalar', 0), ('text', 32), ('text', 4096), ('text', 65536), ('blob', 4096), ('insert', 0)]
    samples = []
    dest = args.output if args.output.is_absolute() else ROOT / args.output
    dest.mkdir(parents=True, exist_ok=True)
    journal = dest / 'samples.jsonl'
    journal.write_text('')
    failure = dest / 'failure.json'
    if failure.exists(): failure.unlink()
    rng = random.Random(219)
    for mode, size in fixtures:
        n = max(1, args.iterations // 10) if size >= 65536 else args.iterations
        expected = n * (n - 1) // 2 if mode == 'scalar' else n * size if mode in ('text', 'blob') else n
        for name, cmd in runners.items():
            output([*cmd, '10', mode, str(size)])
        for repeat in range(args.runs):
            order = list(runners)
            rng.shuffle(order)
            for position, name in enumerate(order):
                before = resource.getrusage(resource.RUSAGE_CHILDREN)
                start = time.perf_counter_ns()
                try:
                    text = output([*runners[name], str(n), mode, str(size)])
                except subprocess.CalledProcessError as error:
                    failure.write_text(json.dumps(dict(implementation=name, fixture=mode, bytes=size,
                                                      iterations=n, run=repeat, returncode=error.returncode)) + '\n')
                    raise
                whole = time.perf_counter_ns() - start
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                elapsed, checksum = map(int, text.split())
                if elapsed <= 0 or checksum != expected: raise RuntimeError(f'Bad result: {name}: {text}')
                samples.append(dict(implementation=name, fixture=mode, bytes=size, iterations=n,
                                    run=repeat, order=position, loop_wall_ns=elapsed, checksum=checksum,
                                    whole_wall_ns=whole, whole_cpu_ns=round((after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) * 1e9)))
                with journal.open('a') as stream:
                    stream.write(json.dumps(samples[-1]) + '\n')
    paths = [p for p in (ROOT / 'bench/alternatives').rglob('*') if p.is_file() and 'target' not in p.parts and '__pycache__' not in p.parts]
    paths += [ROOT / p for p in ('sqlite.goose', 'sqlite.build', 'CMakeLists.txt', 'native/sqlite.c', 'native/sqlite.h', 'GOOSE_REVISION')]
    metadata = dict(timestamp_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), source_commit=output(['git', 'rev-parse', 'HEAD']),
                    source_dirty=bool(output(['git', 'status', '--porcelain'])),
                    goose_revision=(ROOT / 'GOOSE_REVISION').read_text().strip(), goose_sha256=digest(goose),
                    wrapper_versions={'SQLiteCpp': {'version': '3.4.0', 'revision': CPP_REV}, 'rusqlite': '0.41.1', 'Python': sys.version},
                    toolchains={tool: output([tool, '--version']).splitlines()[0] for tool in ('gcc', 'g++', 'rustc', 'cargo', 'cmake')},
                    compiler_flags={'C++ caller': '-O2 -std=c++17, always-on checks', 'SQLiteCpp': '-O2 -DNDEBUG', 'Rust': 'opt-level=2,lto=false,normal assertions active', 'Goose': '--cc gcc -O2; native CMake Release'},
                    sqlite_identities=identities, sqlite_libraries=libraries,
                    binaries={name: digest(cmd[0]) for name, cmd in runners.items()},
                    source_hashes={str(p.relative_to(ROOT)): digest(p) for p in paths},
                    os=platform.platform(), cpu_model=next((v.split(':',1)[1].strip() for v in Path('/proc/cpuinfo').read_text().splitlines() if v.startswith('model name')), ''),
                    affinity=sorted(os.sched_getaffinity(0)), order_seed=219,
                    scope='Goose work_budget=100000000 permits untimed aggregate verification; other hardening retained. In-process checked API paths, not policy-equivalent or universal rankings. Goose retains fixed security/resource policy; other callers use documented defaults. Whole-process times separately reported. Shared host.', samples=samples)
    dest = args.output if args.output.is_absolute() else ROOT / args.output
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'samples.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'Recorded {len(samples)} checked samples in {dest / "samples.json"}')


if __name__ == '__main__': main()
