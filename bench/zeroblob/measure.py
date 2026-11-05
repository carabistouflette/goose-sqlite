#!/usr/bin/env python3
"""Compare copied zeros, zeroblob binding and the existing SQL zeroblob path."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import json
import os
from pathlib import Path
import platform
import random
import resource
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bench/alternatives'))
from paired import run, compiler, digest, engine

SIZES = (0, 4096, 65536, 524288, 1048576)
MODES = ('copy', 'zero', 'sql')
SEED = 219


def iterations(base, size):
    return max(1, base * 4096 // max(size, 4096))


def head():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def native_build(cache):
    caches = list(cache.rglob('CMakeCache.txt'))
    targets = list(cache.rglob('target-goose_sqlite_native-*.json'))
    archives = list(cache.rglob('libgoose_sqlite_native.a'))
    generated = list((cache / 'build/prog').rglob('runner.c'))
    if any(len(items) != 1 for items in (caches, targets, archives, generated)):
        raise RuntimeError('Expected one isolated production native build')
    values = {}
    for line in caches[0].read_text().splitlines():
        if line and not line.startswith(('#', '//')) and '=' in line and ':' in line.split('=', 1)[0]:
            key, value = line.split('=', 1); values[key.split(':', 1)[0]] = value
    if values['CMAKE_BUILD_TYPE'] != 'Release' or values['CMAKE_C_FLAGS_RELEASE'] != '-O3 -DNDEBUG' or values['CMAKE_C_FLAGS']:
        raise RuntimeError('Unexpected native build profile')
    target = json.loads(targets[0].read_text())
    identity, tool = compiler(values['CMAKE_C_COMPILER'])
    record = dict(compiler=identity, build_type=values['CMAKE_BUILD_TYPE'],
                  flags=[[f['fragment'] for f in g.get('compileCommandFragments', [])] for g in target['compileGroups']],
                  archive_sha256=digest(archives[0]), generated_runner_sha256=digest(generated[0]),
                  sqlite_header_sha256=digest(Path(values['SQLite3_INCLUDE_DIR']) / 'sqlite3.h'))
    return record, values, archives[0], tool


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--goose', required=True)
    parser.add_argument('--iterations', type=int, default=32768)
    parser.add_argument('--runs', type=int, default=9)
    parser.add_argument('--cpu', type=int)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 10000000 or not 1 <= args.runs <= 100:
        parser.error('iterations/runs outside range')
    if args.cpu is not None: os.sched_setaffinity(0, {args.cpu})
    dest = args.output if args.output.is_absolute() else ROOT / args.output
    if dest.exists() and any(dest.iterdir()): parser.error('Output must be empty; prior records are never overwritten')
    dest.mkdir(parents=True, exist_ok=True)
    (ROOT / '.build').mkdir(exist_ok=True)
    build = Path(tempfile.mkdtemp(prefix='zeroblob-', dir=ROOT / '.build'))
    source = build / 'source'; cache = build / 'cache'; source.mkdir()
    goose = Path(args.goose).resolve(strict=True)
    sources = ['CMakeLists.txt', 'sqlite.goose', 'sqlite.build', 'GOOSE_REVISION', 'scripts/native-manifest.py']
    sources += [str(p.relative_to(ROOT)) for p in (ROOT / 'native').rglob('*') if p.is_file()]
    sources += [str(p.relative_to(ROOT)) for p in (ROOT / 'bench/zeroblob').glob('*') if p.is_file()]
    sources += ['bench/alternatives/paired.py', 'bench/alternatives/measure.py']
    source_commit = head()
    hashes = {name: digest(ROOT / name) for name in sources}
    for name in sources:
        path = source / name; path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, path)
        if digest(path) != hashes[name]: raise RuntimeError('Source changed while freezing inputs')
    env = os.environ.copy()
    cleared = ('CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'CC', 'CXX', 'CMAKE_GENERATOR',
               'CMAKE_TOOLCHAIN_FILE', 'CMAKE_PREFIX_PATH', 'CMAKE_C_COMPILER_LAUNCHER')
    for key in cleared: env.pop(key, None)
    env['GOOSE_HOME'] = str(cache)
    metadata = dict(source_commit=source_commit, source_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)),
                    source_hashes=hashes, parent_started_utc_ns=time.time_ns(), iterations=args.iterations, runs=args.runs,
                    sizes=list(SIZES), modes=list(MODES), order_seed=SEED, affinity=sorted(os.sched_getaffinity(0)),
                    os=platform.platform(), cpu_model=next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), ''),
                    governor={str(cpu): (Path(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor').read_text().strip() if Path(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor').exists() else None) for cpu in os.sched_getaffinity(0)},
                    load_before=list(os.getloadavg()), cleared_build_environment=list(cleared),
                    scope='Six API paths; in-memory reused SELECT, owned output, every byte checked inside timing. Copy input and all output buffers preallocated. Lifecycle and same-statement priming excluded. Shared host; no exclusive-core, equal-policy, engine-speedup or incremental-RSS claim.')
    replacements = [(str(build), '$BUILD'), (str(goose), '$GOOSE'),
                    (str(goose.parent.parent), '$GOOSE_TOOLCHAIN'), (str(ROOT), '$REPO')]

    def clean(value):
        if isinstance(value, str):
            for old, new in replacements: value = value.replace(old, new)
        elif isinstance(value, list): value = [clean(v) for v in value]
        elif isinstance(value, dict): value = {k: clean(v) for k, v in value.items()}
        return value

    def write(name, value):
        (dest / name).write_text(json.dumps(clean(value), indent=2) + '\n')

    phase = dict(phase='build'); samples = []; journal = dest / 'samples.jsonl'; journal.write_text('')
    write('metadata.json', metadata)
    try:
        version, _ = run([goose, '--version']); pin = (source / 'GOOSE_REVISION').read_text().strip()
        reported = version.split()[1]
        if len(reported) < 7 or not pin.startswith(reported): raise RuntimeError('Goose binary does not match the compiler pin')
        metadata['goose'] = dict(revision=pin, version=version.strip(), sha256=digest(goose))
        run(['python3', 'scripts/native-manifest.py', '--check'], cwd=source, env=env)
        goose_command = [str(goose), 'build', 'bench/zeroblob/runner.goose', '--cc', 'gcc', '-O2', '-o', str(build / 'goose')]
        metadata['build_commands'] = [['python3', 'scripts/native-manifest.py', '--check'], goose_command]
        output, diagnostics = run(goose_command, cwd=source, env=env)
        (build / 'goose-build.log').write_text(output + diagnostics)
        native, values, archive, native_cc = native_build(cache); metadata['native_build'] = native
        replacements.extend([(values['SQLite3_INCLUDE_DIR'], '$SQLITE_INCLUDE'),
                             (values['SQLite3_LIBRARY'], '$SQLITE_LIBRARY')])
        cc_identity, cc = compiler('gcc')
        if cc_identity != native['compiler']: raise RuntimeError('Goose native and raw compilers differ')
        flags = ['-O2', '-std=c11', '-Wall', '-Wextra', '-Werror', '-UNDEBUG']
        for name, extra in [('raw', []), ('diagnostic', ['-DGQ_DIAGNOSTIC'])]:
            command = [str(cc), *flags, *extra, '-I', values['SQLite3_INCLUDE_DIR'], 'bench/zeroblob/raw.c',
                       *([str(archive)] if extra else []), values['SQLite3_LIBRARY'], '-pthread', '-lm', '-o', str(build / name)]
            metadata['build_commands'].append(command)
            run(command, cwd=source, env=env)
        binaries = {name: build / name for name in ('goose', 'raw', 'diagnostic')}
        libraries = {name: engine(path) for name, path in binaries.items()}
        if len({v['sha256'] for v in libraries.values()}) != 1: raise RuntimeError('SQLite loaded objects differ')
        identity, _ = run([binaries['raw'], 'identity'], env=env)
        diag_identity, _ = run([binaries['diagnostic'], 'identity'], env=env)
        if identity != diag_identity: raise RuntimeError('SQLite runtime identities differ')
        metadata.update(sqlite_identity=identity.splitlines(), sqlite_libraries=libraries,
                        binary_sha256={name: digest(path) for name, path in binaries.items()},
                        compiler_flags={'Goose': '--cc gcc -O2', 'raw C': flags, 'diagnostic': flags + ['-DGQ_DIAGNOSTIC', '$NATIVE_ARCHIVE']},
                        compiler=cc_identity, build_label=build.name,
                        rss_scope='GNU time %M: whole-process peak KiB including setup/priming/verification and small native launch footprint, not SQLite binding allocations')
        tools = {}
        for name in ('cmake', '/usr/bin/time'):
            tool_identity, path = compiler(name); tools[name] = (path, tool_identity['sha256'])
            metadata.setdefault('tools', {})[tool_identity['file']] = tool_identity
        write('metadata.json', metadata)
        rng = random.Random(SEED)
        cases = [(name, mode) for name in ('goose', 'raw') for mode in MODES]
        for size in SIZES:
            n = iterations(args.iterations, size)
            for name, mode in cases:
                phase = dict(phase='warmup', implementation=name, mode=mode, bytes=size)
                text, error = run([binaries[name], 1, mode, size], env=env)
                elapsed, checksum = map(int, text.split())
                if error or elapsed <= 0 or checksum != size + 1: raise RuntimeError('Invalid warmup')
            for repeat in range(args.runs):
                order = cases.copy(); rng.shuffle(order)
                for position, (name, mode) in enumerate(order):
                    phase = dict(phase='sample', implementation=name, mode=mode, bytes=size, iterations=n, run=repeat, order=position)
                    rss = build / 'rss.txt'; before = resource.getrusage(resource.RUSAGE_CHILDREN)
                    started_utc_ns = time.time_ns(); start = time.perf_counter_ns()
                    text, error = run(['/usr/bin/time', '-o', rss, '-f', '%M', '--', binaries[name], n, mode, size], env=env)
                    whole = time.perf_counter_ns() - start; ended_utc_ns = time.time_ns(); after = resource.getrusage(resource.RUSAGE_CHILDREN)
                    elapsed, checksum = map(int, text.split()); peak = int(rss.read_text().strip())
                    if error or elapsed <= 0 or checksum != n * (size + 1) or peak < 0: raise RuntimeError('Invalid measured result')
                    sample = dict(phase, command=[f'${name.upper()}_BINARY', str(n), mode, str(size)],
                                  loop_wall_ns=elapsed, checksum=checksum, raw_stdout=text.strip(), peak_rss_kib=peak,
                                  whole_wall_ns=whole, whole_start_utc_ns=started_utc_ns, whole_end_utc_ns=ended_utc_ns,
                                  whole_cpu_ns=round((after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) * 1e9))
                    samples.append(sample)
                    with journal.open('a') as stream: stream.write(json.dumps(sample) + '\n')
        diagnostics = []
        for size in SIZES:
            for driver in ('raw', 'checked'):
                for mode in MODES:
                    phase = dict(phase='allocator diagnostic', driver=driver, mode=mode, bytes=size)
                    text, error = run([binaries['diagnostic'], driver, mode, size], env=env)
                    record = json.loads(text)
                    expected_driver = 'raw-c-api' if driver == 'raw' else 'checked-native-abi'
                    if error or record['bytes'] != size or record['verified_bytes'] != size or record['mode'] != mode or record['driver'] != expected_driver or record['sqlite_before'] <= 0:
                        raise RuntimeError('Invalid allocator diagnostic')
                    if record['sqlite_after_bind'] - record['sqlite_before'] != record['sqlite_delta']:
                        raise RuntimeError('Invalid allocator delta')
                    diagnostics.append(record)
        phase = dict(phase='final verification')
        if head() != source_commit or any(digest(ROOT / name) != sha or digest(source / name) != sha for name, sha in hashes.items()):
            raise RuntimeError('Source changed during this series')
        if any(digest(path) != metadata['binary_sha256'][name] or engine(path) != libraries[name] for name, path in binaries.items()):
            raise RuntimeError('Measured binary or engine changed')
        if digest(native_cc) != cc_identity['sha256'] or digest(cc) != cc_identity['sha256'] or digest(goose) != metadata['goose']['sha256']:
            raise RuntimeError('Compiler changed')
        if any(digest(path) != sha for path, sha in tools.values()): raise RuntimeError('Measurement tool changed')
        metadata.update(parent_completed_utc_ns=time.time_ns(), load_after=list(os.getloadavg()), complete=True,
                        samples=samples, sample_count=len(samples), allocator_diagnostics=diagnostics,
                        allocator_scope='Separate single-connection native processes, raw C and checked ABI. SQLITE_CONFIG_MEMSTATUS enabled before initialization; delta only spans binding, before step/materialization. All bytes verified afterward. SQLite allocator accounting excludes source/output malloc and Goose runtime heap.')
        write('samples.json', metadata); write('metadata.json', {k: v for k, v in metadata.items() if k != 'samples'})
        print(f'Recorded {len(samples)} checked samples and {len(diagnostics)} allocator probes in {dest}')
    except BaseException as error:
        write('failure.json', dict(phase, error_type=type(error).__name__, error=str(error), checked_samples=len(samples)))
        write('metadata.json', dict(metadata, complete=False)); raise


if __name__ == '__main__':
    main()
