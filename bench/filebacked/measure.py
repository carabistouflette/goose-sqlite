#!/usr/bin/env python3
"""Record checked file-backed transaction and controlled-BUSY API comparisons."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import resource
import shutil
import signal
import sqlite3
import struct
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bench/alternatives'))
from paired import compiler, digest, engine, run, sqlite_identity  # noqa: E402

CPP_REV = 'df0a28ca9733f687ab7ce77f070c0df84368a45e'
PAYLOAD = b'\0' + b'x' * 126 + b'\xff'
IMPLEMENTATIONS = ('goose', 'raw-c-api', 'sqlitecpp', 'rusqlite', 'python')
JOURNALS = ('delete', 'wal')
MODES = ('commit', 'rollback', 'busy')
SEED = 219


def git(*arguments):
    return run(['git', *arguments], cwd=ROOT)[0].strip()


def source_paths():
    paths = [ROOT / name for name in ('sqlite.goose', 'sqlite.build', 'CMakeLists.txt',
                                      'GOOSE_REVISION', 'Makefile', 'scripts/native-manifest.py',
                                      '.github/workflows/ci.yml',
                                      'bench/alternatives/paired.py',
                                      'bench/alternatives/measure.py')]
    for directory in ('native', 'bench/filebacked'):
        paths.extend(p for p in (ROOT / directory).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts and 'target' not in p.parts)
    for path in paths:
        if path.is_symlink():
            raise RuntimeError('Source snapshots accept regular files only')
    return sorted(set(paths))


def hash_sources():
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in source_paths()}


def clean_environment():
    env = os.environ.copy()
    cleared = []
    for name in list(env):
        if (name in ('CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'CC', 'CXX',
                     'CMAKE_GENERATOR', 'CMAKE_TOOLCHAIN_FILE', 'CMAKE_PREFIX_PATH',
                     'CMAKE_C_COMPILER_LAUNCHER', 'CMAKE_CXX_COMPILER_LAUNCHER',
                     'CARGO_BUILD_TARGET', 'CARGO_TARGET_DIR', 'RUSTFLAGS',
                     'CARGO_ENCODED_RUSTFLAGS', 'LD_PRELOAD', 'LD_LIBRARY_PATH')
                or name.startswith('CARGO_PROFILE_RELEASE_')):
            cleared.append(name)
            env.pop(name)
    env.update(CARGO_ENCODED_RUSTFLAGS='', CARGO_INCREMENTAL='1',
               RUSTC_WRAPPER='', RUSTC_WORKSPACE_WRAPPER='')
    return env, sorted(cleared)


def cache_values(path):
    values = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith(('#', '//')) and '=' in line and ':' in line.split('=', 1)[0]:
            key, value = line.split('=', 1)
            values[key.split(':', 1)[0]] = value
    return values


def build_all(source, output, goose, env, metadata, save):
    def command(cmd, cwd=source, timeout=600):
        metadata.setdefault('build_commands', []).append([str(v) for v in cmd])
        save()
        stdout, stderr = run(cmd, cwd=cwd, env=env, timeout=timeout)
        with (output / 'build.log').open('a') as log:
            log.write(stdout + stderr)
        return stdout.strip()

    version = command([goose, '--version'])
    import re
    reported = re.match(r'goose ([0-9a-f]{7,40})(?:\s|$)', version)
    declared = (source / 'GOOSE_REVISION').read_text().strip()
    if reported is None or not declared.startswith(reported[1]):
        raise RuntimeError('Actual Goose compiler does not match GOOSE_REVISION')
    metadata['goose'] = dict(revision=declared, version=version, sha256=digest(goose))
    cache = output / 'goose-cache'
    env['GOOSE_HOME'] = str(cache)
    command(['python3', 'scripts/native-manifest.py', '--check'])
    command([goose, 'build', 'bench/filebacked/runner.goose', '--cc', 'gcc',
             '-O2', '-o', output / 'goose'])
    caches = list(cache.rglob('CMakeCache.txt'))
    targets = list(cache.rglob('target-goose_sqlite_native-*.json'))
    archives = list(cache.rglob('libgoose_sqlite_native.a'))
    generated = list((cache / 'build/prog').rglob('runner.c'))
    if any(len(paths) != 1 for paths in (caches, targets, archives, generated)):
        raise RuntimeError('Expected one isolated Goose native build and generated caller')
    values = cache_values(caches[0])
    if (values['CMAKE_BUILD_TYPE'] != 'Release' or values['CMAKE_C_FLAGS']
            or values['CMAKE_C_FLAGS_RELEASE'] != '-O3 -DNDEBUG'):
        raise RuntimeError('Unexpected Goose native compiler profile')
    native_compiler, _ = compiler(values['CMAKE_C_COMPILER'])
    target = json.loads(targets[0].read_text())
    metadata['native_build'] = dict(compiler=native_compiler,
        flags=[[f['fragment'] for f in group.get('compileCommandFragments', [])]
               for group in target['compileGroups']],
        build_type=values['CMAKE_BUILD_TYPE'], archive_sha256=digest(archives[0]),
        generated_caller_sha256=digest(generated[0]),
        sqlite_header_sha256=digest(Path(values['SQLite3_INCLUDE_DIR']) / 'sqlite3.h'))
    command(['gcc', '-std=c11', '-O2', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
             source / 'bench/filebacked/policy.c', archives[0], '-lsqlite3', '-pthread',
             '-lm', '-o', output / 'policy'])

    cpp = ROOT / '.build/alternatives/SQLiteCpp'
    if not (cpp / '.git').exists():
        raise RuntimeError('Pinned SQLiteCpp source cache missing; run the existing alternative setup first')
    if git('-C', cpp, 'rev-parse', 'HEAD') != CPP_REV or git('-C', cpp, 'status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('SQLiteCpp cache must be clean at its pinned revision')
    cpp_sources = git('-C', cpp, 'ls-files').splitlines()
    metadata['sqlitecpp_sources'] = {name: digest(cpp / name) for name in cpp_sources
                                     if (cpp / name).is_file()}
    cpp_build = output / 'cpp-build'
    command(['cmake', '-S', cpp, '-B', cpp_build, '-DSQLITECPP_INTERNAL_SQLITE=OFF',
             '-DSQLITECPP_BUILD_TESTS=OFF', '-DSQLITECPP_BUILD_EXAMPLES=OFF',
             '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_FLAGS_RELEASE=-O2 -DNDEBUG',
             '-DCMAKE_CXX_FLAGS=', '-DCMAKE_CXX_COMPILER=g++', '-DCMAKE_C_COMPILER=gcc',
             '-DCMAKE_CXX_COMPILER_LAUNCHER=', '-DCMAKE_C_COMPILER_LAUNCHER='])
    command(['cmake', '--build', cpp_build, '--parallel', '2'])
    cpp_values = cache_values(cpp_build / 'CMakeCache.txt')
    if (cpp_values.get('CMAKE_BUILD_TYPE') != 'Release'
            or cpp_values.get('SQLITECPP_INTERNAL_SQLITE') != 'OFF'
            or cpp_values.get('CMAKE_CXX_FLAGS_RELEASE') != '-O2 -DNDEBUG'
            or cpp_values.get('CMAKE_CXX_FLAGS')):
        raise RuntimeError('Unexpected SQLiteCpp external-engine compiler profile')
    metadata['sqlitecpp_build'] = dict(revision=CPP_REV,
        compiler=compiler(cpp_values['CMAKE_CXX_COMPILER'])[0],
        flags=cpp_values['CMAKE_CXX_FLAGS_RELEASE'],
        archive_sha256=digest(cpp_build / 'libSQLiteCpp.a'))
    for name, flags in (('raw-c-api', []), ('sqlitecpp', ['-DUSE_SQLITECPP', '-I' + str(cpp / 'include')])):
        cmd = ['g++', '-std=c++17', '-O2', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
               *flags, source / 'bench/filebacked/native.cpp']
        if name == 'sqlitecpp':
            cmd.append(cpp_build / 'libSQLiteCpp.a')
        command([*cmd, '-lsqlite3', '-o', output / name])

    rustc = Path(command(['rustc', '--print', 'sysroot'])) / 'bin/rustc'
    env['RUSTC'] = str(rustc)
    verbose = command([rustc, '-vV'])
    host = next(line.split(': ', 1)[1] for line in verbose.splitlines() if line.startswith('host: '))
    metadata['rustc'] = dict(version=verbose, sha256=digest(rustc))
    command(['cargo', 'build', '--locked', '--release', '--target', host,
             '--target-dir', output / 'rust-target', '--manifest-path',
             source / 'bench/filebacked/rust/Cargo.toml', '--config', 'profile.release.opt-level=2',
             '--config', 'profile.release.lto="thin"', '--config', 'profile.release.codegen-units=16',
             '--config', 'profile.release.incremental=true'])
    rust_binary = output / 'rust-target' / host / 'release/sqlite-filebacked-bench'
    metadata['rust_dependencies'] = tomllib.loads((source / 'bench/filebacked/rust/Cargo.lock').read_text())['package']
    metadata['rust_profile'] = dict(opt_level=2, lto='thin', codegen_units=16,
                                    incremental=True, bundled_sqlite=False,
                                    cargo_lock_sha256=digest(source / 'bench/filebacked/rust/Cargo.lock'))
    metadata['tools'] = {}
    for name in ('gcc', 'g++', 'cmake', 'cargo', 'git', 'python3', '/usr/bin/time'):
        actual = Path(shutil.which(name) or name).resolve(strict=True)
        stdout = command([actual, '--version'], timeout=30)
        metadata['tools'][name] = dict(file=actual.name, version=stdout.splitlines()[0], sha256=digest(actual))
    runners = {'goose': [output / 'goose'], 'raw-c-api': [output / 'raw-c-api'],
               'sqlitecpp': [output / 'sqlitecpp'], 'rusqlite': [rust_binary],
               'python': [Path(sys.executable).resolve(), '-I', source / 'bench/filebacked/python.py']}
    import _sqlite3
    objects = {name: engine(cmd[0]) for name, cmd in runners.items() if name != 'python'}
    objects['python'] = engine(Path(_sqlite3.__file__))
    objects['policy'] = engine(output / 'policy')
    if len({value['sha256'] for value in objects.values()}) != 1:
        raise RuntimeError('Runners, Python and policy probe load different SQLite objects')
    metadata['sqlite_libraries'] = objects
    links = command(['ldd', output / 'goose'])
    library = Path(next(line.split('=>', 1)[1].split('(', 1)[0].strip()
                        for line in links.splitlines() if 'libsqlite3' in line and '=>' in line)).resolve()
    mapped = set()
    for line in Path('/proc/self/maps').read_text().splitlines():
        fields = line.split(None, 5)
        if len(fields) == 6 and 'libsqlite3' in fields[5]:
            if fields[5].endswith(' (deleted)'):
                raise RuntimeError('Parent SQLite object was replaced during recording')
            mapped.add(Path(fields[5]).resolve())
    if mapped != {library} or digest(next(iter(mapped))) != metadata['sqlite_libraries']['goose']['sha256']:
        raise RuntimeError('Parent seeding/verifier engine differs from measured child engine')
    metadata['parent_engine'] = dict(file=library.name, sha256=digest(library), mapped_object_verified=True)
    metadata['sqlite_identity'] = sqlite_identity(library)
    metadata['engine_identity_scope'] = 'Runtime identity/options explicitly queried from the common loaded object; inferred for each runner/probe from its exact matching object hash.'
    metadata['binary_sha256'] = {name: digest(cmd[0]) for name, cmd in runners.items()}
    metadata['binary_sha256']['policy'] = digest(output / 'policy')
    metadata['python'] = dict(version=sys.version, executable_sha256=digest(sys.executable),
                              extension_file=Path(_sqlite3.__file__).name,
                              extension_sha256=digest(_sqlite3.__file__), isolated=True,
                              optimize=command([sys.executable, '-I', '-c', 'import sys; print(sys.flags.optimize)']))
    if metadata['python']['optimize'] != '0':
        raise RuntimeError('Python verification must not be optimized away')
    return runners, cpp, rustc


def files(path):
    result = {}
    for suffix in ('', '-wal', '-shm', '-journal'):
        file = Path(str(path) + suffix)
        result['database' if not suffix else suffix[1:]] = (
            dict(bytes=file.stat().st_size, sha256=digest(file)) if file.exists() else None)
    return result


def seed(path, journal):
    if path.exists():
        raise RuntimeError('Refusing to reuse a database fixture')
    db = sqlite3.connect(path, isolation_level=None, timeout=0)
    try:
        db.execute('PRAGMA page_size=4096')
        if db.execute('PRAGMA journal_mode=' + journal).fetchone() != (journal,):
            raise RuntimeError('Seed journal mode did not match')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE items(id INTEGER PRIMARY KEY,payload BLOB NOT NULL)')
        db.execute('INSERT INTO items VALUES(-1,?)', (PAYLOAD,))
        if journal == 'wal' and db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone() != (0, 0, 0):
            raise RuntimeError('Seed WAL did not truncate')
    finally:
        db.close()
    initial = files(path)
    if initial['wal'] is not None and initial['wal']['bytes'] != 0:
        raise RuntimeError('Initial WAL must be absent or empty')
    return initial


def verify(path, journal, mode, transactions, batch):
    count = transactions * batch if mode == 'commit' else 1 if mode == 'busy' else 0
    logical = hashlib.sha256()
    checksum = 0
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0)
    try:
        if db.execute('PRAGMA journal_mode').fetchone() != (journal,):
            raise RuntimeError('Runner changed journal mode')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise RuntimeError('Integrity check failed')
        cursor = db.execute('SELECT id,payload FROM items ORDER BY id')
        for expected in range(-1, count):
            row = cursor.fetchone()
            if (row is None or type(row[0]) is not int or type(row[1]) is not bytes
                    or row[0] != expected or row[1] != PAYLOAD):
                raise RuntimeError('Independent stored-data oracle failed')
            logical.update(struct.pack('<q', row[0]))
            logical.update(row[1])
            checksum += row[0] + 2
        if cursor.fetchone() is not None:
            raise RuntimeError('Unexpected additional stored row')
        cursor.close()
    finally:
        db.close()
    return dict(rows=count + 1, checksum=checksum, logical_data_sha256=logical.hexdigest(), integrity='ok')


def policy_expected(journal):
    return f'policy {journal} 2 4096 -2000 1000 1 0 normal 0'


def parse(stdout, implementation, journal, mode, transactions, batch):
    lines = stdout.splitlines()
    if len(lines) != transactions + 2:
        raise RuntimeError('Unexpected runner output line count')
    expected = 'policy inferred' if implementation == 'goose' else policy_expected(journal)
    if lines[0] != expected:
        raise RuntimeError('Runner policy differs from the matched policy')
    if len(lines[1].split()) != 5:
        raise RuntimeError('Malformed runner summary')
    elapsed, checksum, commits, busy, rollbacks = map(int, lines[1].split())
    outcomes = {'commit': (transactions, 0, 0), 'rollback': (0, 0, transactions),
                'busy': (0, transactions, 0)}[mode]
    count = transactions * batch if mode == 'commit' else 1 if mode == 'busy' else 0
    if elapsed <= 0 or checksum != 1 + count * (count + 3) // 2 or (commits, busy, rollbacks) != outcomes:
        raise RuntimeError('Runner counts/checksum do not match workload')
    latencies, codes = [], []
    for line in lines[2:]:
        if len(line.split()) != 2:
            raise RuntimeError('Malformed runner latency/code')
        ns, code = map(int, line.split())
        if ns <= 0 or code < 0 or (mode == 'busy' and (code & 255) != 5) or (mode != 'busy' and code != 0):
            raise RuntimeError('Unexpected transaction latency or result code')
        latencies.append(ns)
        codes.append(code)
    if sum(latencies) > elapsed:
        raise RuntimeError('Per-operation time exceeds enclosing loop time')
    ordered = sorted(latencies)
    quantiles = {label: ordered[math.ceil(fraction * len(ordered)) - 1]
                 for label, fraction in (('p50', .5), ('p95', .95), ('p99', .99))}
    units = 'committed_rows_per_second' if mode == 'commit' else 'rolled_back_transactions_per_second' if mode == 'rollback' else 'rejected_attempts_per_second'
    return dict(loop_wall_ns=elapsed, checksum=checksum, commits=commits, busy=busy,
                rollbacks=rollbacks, automatic_retries=0, latency_ns=latencies,
                result_codes=codes, nearest_rank_latency_ns=quantiles,
                quantile_sample_count=transactions, throughput_unit=units,
                throughput=(transactions * batch if mode == 'commit' else transactions) * 1e9 / elapsed,
                policy_line=lines[0])


def measured(cmd, directory, env, save_failure, timeout=300):
    rss_file = directory / 'rss.txt'
    whole_start_utc_ns = time.time_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter_ns()
    process = subprocess.Popen(['/usr/bin/time', '-o', str(rss_file), '-f', '%M', '--', *map(str, cmd)],
                               env=env, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException as error:
        timed_out = isinstance(error, subprocess.TimeoutExpired)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        save_failure(stdout, stderr, process.returncode, timed_out)
        raise
    elapsed = time.perf_counter_ns() - started
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    (directory / 'stdout.txt').write_text(stdout)
    (directory / 'stderr.txt').write_text(stderr)
    if process.returncode:
        save_failure(stdout, stderr, process.returncode, timed_out)
        raise RuntimeError('Measured child failed; database and diagnostics retained')
    peak = int(rss_file.read_text().strip())
    if peak < 0:
        raise RuntimeError('Invalid peak RSS')
    return dict(raw_stdout=stdout, raw_stderr=stderr, whole_start_utc_ns=whole_start_utc_ns,
                whole_end_utc_ns=time.time_ns(), whole_wall_ns=elapsed,
                whole_cpu_ns=int((after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) * 1e9),
                peak_rss_kib=peak, child_exit_status=process.returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--goose', required=True, type=Path)
    parser.add_argument('--transactions', type=int, default=128)
    parser.add_argument('--batch', type=int, default=16)
    parser.add_argument('--runs', type=int, default=9)
    parser.add_argument('--cpu', type=int)
    parser.add_argument('--journals', choices=('both', 'delete', 'wal'), default='both')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--smoke', action='store_true', help='Permit dirty development source; not principal timing')
    args = parser.parse_args()
    if any(os.environ.get(name) for name in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'LD_AUDIT')):
        parser.error('Run the recorder without loader overrides so parent and child engines agree')
    if not 1 <= args.transactions <= 10000 or not 1 <= args.batch <= 1024 or args.transactions * args.batch > 1000000 or not 1 <= args.runs <= 100:
        parser.error('transaction/batch/run bounds exceeded')
    if args.cpu is not None:
        if args.cpu not in os.sched_getaffinity(0):
            parser.error('CPU is outside allowed affinity')
        os.sched_setaffinity(0, {args.cpu})
    output = args.output.resolve()
    if output.is_relative_to(ROOT) and not output.is_relative_to(ROOT / '.build'):
        parser.error('Use an ignored .build output or a directory outside the source checkout')
    goose = args.goose.resolve(strict=True)
    head, dirty = git('rev-parse', 'HEAD'), git('status', '--porcelain')
    if dirty and not args.smoke:
        parser.error('Principal recording requires clean committed source; --smoke permits development source')
    journals = JOURNALS if args.journals == 'both' else (args.journals,)
    sources = hash_sources()
    if not args.smoke:
        for name, value in sources.items():
            committed = subprocess.check_output(['git', 'show', head + ':' + name], cwd=ROOT)
            if hashlib.sha256(committed).hexdigest() != value:
                raise RuntimeError('Principal source differs from its recorded Git blob: ' + name)
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'
    env, cleared = clean_environment()
    replacements = [(str(source), '$SOURCE'), (str(output), '$BUILD'),
                    (str(goose), '$GOOSE'), (str(goose.parent.parent), '$GOOSE_SOURCE'),
                    (str(ROOT), '$REPO'), (str(Path.home()), '$HOME')]
    def normalize(value):
        if isinstance(value, Path):
            return normalize(str(value))
        if isinstance(value, str):
            for old, new in replacements:
                value = value.replace(old, new)
            return value
        if isinstance(value, dict):
            return {str(k): normalize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        return value
    metadata = dict(source_commit=head, source_dirty=bool(dirty), source_hashes=sources,
                    parent_started_utc_ns=time.time_ns(), complete=False,
                    development_smoke=args.smoke, transactions=args.transactions,
                    batch=args.batch, runs=args.runs, journals=list(journals),
                    expected_sample_count=len(journals) * len(MODES) * len(IMPLEMENTATIONS) * args.runs,
                    order_seed=SEED,
                    affinity=sorted(os.sched_getaffinity(0)),
                    governor={str(cpu): (Path(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor').read_text().strip()
                                         if Path(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor').exists() else None)
                              for cpu in os.sched_getaffinity(0)},
                    os=platform.platform(),
                    cpu_model=next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), ''),
                    load_before=list(os.getloadavg()), cleared_environment=cleared,
                    scope='Selected journal modes crossed with three file-backed workloads per caller, warm OS cache, matched FULL policy. BUSY is controlled rejection and same-connection recovery, not concurrent throughput. No power-loss, exclusive-core or universal ranking claim.',
                    rss_scope='GNU time whole-child-lifetime peak KiB, including startup/setup/verification/cleanup and small launcher footprint; not incremental binding heap.',
                    database_retention='Successful fixture databases/sidecars removed after full independent verification and recorded hashes. Failed fixtures and diagnostics retained.',
                    warmups=[], sample_count=0)
    def save():
        (output / 'metadata.json').write_text(json.dumps(normalize(metadata), indent=2) + '\n')
    save()
    samples = []
    try:
        for name, value in sources.items():
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
            if digest(target) != value:
                raise RuntimeError('Source changed while freezing snapshot')
        filesystem = json.loads(run(['findmnt', '-J', '-T', output], env=env)[0])
        metadata['filesystem'] = filesystem
        if any(fs['fstype'] in ('tmpfs', 'ramfs') for fs in filesystem['filesystems']):
            raise RuntimeError('Memory-backed output filesystem is outside this file-backed comparison')
        metadata['storage_scope'] = 'Observed mount/filesystem is recorded; device hardware, controller caches and physical durability are unverified. Overlay/network mounts, if present, cannot establish physical-disk behavior.'
        runners, cpp, rustc = build_all(source, output, goose, env, metadata, save)
        metadata['policy_preflights'] = {}
        for journal in journals:
            path = output / ('policy-' + journal + '.db')
            initial = seed(path, journal)
            stdout, stderr = run([output / 'policy', path], env=env)
            if stdout.strip() != policy_expected(journal) or stderr:
                raise RuntimeError('Goose native policy probe does not match required policies')
            metadata['policy_preflights'][journal] = dict(raw_stdout=stdout, raw_stderr=stderr,
                                                        initial_files=initial, final_files=files(path),
                                                        scope='Separate process: authorizer denial checked before test-only removal for fixed policy reads; actual Goose settings inferred from same adapter archive/options/engine.')
            for suffix in ('', '-wal', '-shm', '-journal'):
                Path(str(path) + suffix).unlink(missing_ok=True)
        save()
        rng = random.Random(SEED)
        journal_file = output / 'samples.jsonl'
        journal_file.touch(exist_ok=False)
        index = 0
        def sample(implementation, journal, mode, count, batch, phase, repeat, position):
            nonlocal index
            index += 1
            directory = output / 'fixtures' / f'{index:05d}-{phase}-{journal}-{mode}-{implementation}'
            directory.mkdir(parents=True, exist_ok=False)
            path = directory / 'database.db'
            initial = seed(path, journal)
            context = dict(implementation=implementation, journal=journal, mode=mode,
                           transactions=count, batch=batch, phase=phase, run=repeat, order=position,
                           fixture_directory=directory, initial_files=initial)
            metadata['active_sample'] = context
            save()
            def failure(stdout, stderr, code, timed_out):
                metadata['failure'] = dict(**context, raw_stdout=stdout, raw_stderr=stderr,
                                           child_exit_status=code, timed_out=timed_out)
                (directory / 'stdout.txt').write_text(stdout)
                (directory / 'stderr.txt').write_text(stderr)
                save()
            result = measured([*runners[implementation], path, mode, str(count), str(batch)], directory, env, failure)
            parsed = parse(result['raw_stdout'], implementation, journal, mode, count, batch)
            after_child = files(path)
            verified = verify(path, journal, mode, count, batch)
            if verified['checksum'] != parsed['checksum']:
                raise RuntimeError('Independent checksum differs from child')
            record = dict(**context, **result, **parsed, verified=verified,
                          files_after_child=after_child, files_after_verification=files(path))
            for suffix in ('', '-wal', '-shm', '-journal'):
                Path(str(path) + suffix).unlink(missing_ok=True)
            metadata.pop('active_sample', None)
            return normalize(record)
        for journal in journals:
            for mode in MODES:
                for implementation in IMPLEMENTATIONS:
                    metadata['warmups'].append(sample(implementation, journal, mode, 1, 2, 'warmup', -1, -1))
                for repeat in range(args.runs):
                    order = list(IMPLEMENTATIONS)
                    rng.shuffle(order)
                    for position, implementation in enumerate(order):
                        record = sample(implementation, journal, mode, args.transactions, args.batch,
                                        'sample', repeat, position)
                        samples.append(record)
                        with journal_file.open('a') as stream:
                            stream.write(json.dumps(record) + '\n')
                            stream.flush()
                        metadata['sample_count'] = len(samples)
                        save()
        if hash_sources() != sources or git('rev-parse', 'HEAD') != head or git('status', '--porcelain') != dirty:
            raise RuntimeError('Working source/HEAD/dirty state changed during recording')
        for name, value in sources.items():
            if digest(source / name) != value:
                raise RuntimeError('Frozen source changed during recording')
        for name, cmd in runners.items():
            if digest(cmd[0]) != metadata['binary_sha256'][name]:
                raise RuntimeError('Runner binary changed during recording')
            if name != 'python' and engine(cmd[0]) != metadata['sqlite_libraries'][name]:
                raise RuntimeError('Runner engine changed during recording')
        import _sqlite3
        if engine(_sqlite3.__file__) != metadata['sqlite_libraries']['python'] or digest(_sqlite3.__file__) != metadata['python']['extension_sha256']:
            raise RuntimeError('Python SQLite extension/engine changed during recording')
        if engine(output / 'policy') != metadata['sqlite_libraries']['policy'] or digest(output / 'policy') != metadata['binary_sha256']['policy']:
            raise RuntimeError('Policy probe/engine changed during recording')
        if digest(goose) != metadata['goose']['sha256'] or digest(rustc) != metadata['rustc']['sha256']:
            raise RuntimeError('Compiler binary changed during recording')
        if git('-C', cpp, 'rev-parse', 'HEAD') != CPP_REV or git('-C', cpp, 'status', '--porcelain', '--untracked-files=all'):
            raise RuntimeError('SQLiteCpp source changed during recording')
        for name, value in metadata['sqlitecpp_sources'].items():
            if digest(cpp / name) != value:
                raise RuntimeError('SQLiteCpp dependency bytes changed during recording')
        for name, identity in metadata['tools'].items():
            actual = Path(shutil.which(name) or name).resolve(strict=True)
            if digest(actual) != identity['sha256']:
                raise RuntimeError('Build/measurement tool changed during recording')
        archives = list((output / 'goose-cache').rglob('libgoose_sqlite_native.a'))
        generated = list((output / 'goose-cache/build/prog').rglob('runner.c'))
        if (len(archives) != 1 or digest(archives[0]) != metadata['native_build']['archive_sha256']
                or len(generated) != 1 or digest(generated[0]) != metadata['native_build']['generated_caller_sha256']
                or digest(output / 'cpp-build/libSQLiteCpp.a') != metadata['sqlitecpp_build']['archive_sha256']):
            raise RuntimeError('Generated caller or native archives changed during recording')
        if len(samples) != metadata['expected_sample_count']:
            raise RuntimeError('Recording did not complete all requested cases')
        metadata['complete'] = True
        metadata['parent_completed_utc_ns'] = time.time_ns()
        metadata['load_after'] = list(os.getloadavg())
        (output / 'samples.json').write_text(json.dumps(normalize(dict(metadata, samples=samples)), indent=2) + '\n')
    except BaseException as error:
        metadata['complete'] = False
        metadata.setdefault('failure', metadata.get('active_sample', {}).copy())['error'] = str(error)
        (output / 'failure.json').write_text(json.dumps(normalize(metadata['failure']), indent=2) + '\n')
        raise
    finally:
        save()
    print(f'Completed {len(samples)} checked samples across {len(journals) * len(MODES)} cases and five callers')


if __name__ == '__main__':
    main()
