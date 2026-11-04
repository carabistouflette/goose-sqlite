#!/usr/bin/env python3
"""Compare two frozen Goose revisions in checked, shuffled before/after pairs."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import random
import re
import resource
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time

from measure import ROOT, digest, engine

SOURCES = ('sqlite.goose', 'sqlite.build', 'CMakeLists.txt', 'native',
           'GOOSE_REVISION', 'scripts/native-manifest.py', 'bench/alternatives/runner.goose')
# Keep the exact fixtures, iteration scaling and checksums of measure.py.
FIXTURES = (('prepare', 0), ('scalar', 0), ('text', 32), ('text', 4096),
            ('text', 65536), ('blob', 4096), ('insert', 0), ('scan', 128),
            ('lookup', 128), ('batch', 128))
SEED = 219


def run(cmd, cwd=ROOT, env=None, timeout=300):
    """Capture diagnostics and reap the entire owned process group on timeout."""
    process = subprocess.Popen([str(v) for v in cmd], cwd=cwd, env=env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        if isinstance(error, subprocess.TimeoutExpired):
            raise RuntimeError(f'Command timed out ({timeout}s): {cmd!r}\n{stdout}\n{stderr}') from error
        raise
    if process.returncode:
        raise RuntimeError(f'Command failed ({process.returncode}): {cmd!r}\n{stdout}\n{stderr}')
    return stdout, stderr


def git(*args):
    return subprocess.check_output(['git', *map(str, args)], cwd=ROOT)


def revision(value):
    resolved = git('rev-parse', '--verify', '--end-of-options', value + '^{commit}').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', resolved):
        raise ValueError('Expected a full commit object ID')
    return resolved


def snapshot(commit, directory):
    entries = git('ls-tree', '-rz', commit, '--', *SOURCES).split(b'\0')
    blobs = {}
    for entry in filter(None, entries):
        attributes, name = entry.split(b'\t', 1)
        mode, kind, object_id = attributes.decode().split()
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise RuntimeError('Build snapshots accept regular source files only')
        blobs[name.decode()] = object_id
    archive = git('archive', '--format=tar', commit, '--', *SOURCES)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for member in stream:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts:
                raise RuntimeError('Unsafe archive path')
            if member.isdir():
                continue
            if not member.isfile() or member.name not in blobs:
                raise RuntimeError('Unexpected archive member')
            target = directory.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(stream.extractfile(member).read())
    hashes = {name: digest(directory / name) for name in blobs}
    record = dict(commit=commit, archive_sha256=hashlib.sha256(archive).hexdigest(),
                  source_hashes=hashes, git_blobs=blobs)
    verify_snapshot(directory, record)
    return record


def verify_snapshot(directory, record):
    if set(p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()) != set(record['git_blobs']):
        raise RuntimeError('Frozen source file set changed')
    if revision(record['commit']) != record['commit']:
        raise RuntimeError('Source commit changed')
    for name, blob in record['git_blobs'].items():
        committed = hashlib.sha256(git('cat-file', 'blob', blob)).hexdigest()
        if committed != record['source_hashes'][name] or digest(directory / name) != committed:
            raise RuntimeError(f'Frozen source does not match committed object: {name}')


def compiler(path):
    actual = Path(shutil.which(str(path)) or str(path)).resolve(strict=True)
    version, _ = run([actual, '--version'])
    return dict(file=actual.name, version=version.splitlines()[0], sha256=digest(actual)), actual


def build(source, cache, binary, goose, env):
    child_env = dict(env, GOOSE_HOME=str(cache))
    run(['python3', 'scripts/native-manifest.py', '--check'], cwd=source, env=child_env)
    stdout, stderr = run([goose, 'build', 'bench/alternatives/runner.goose', '--cc', 'gcc',
                          '-O2', '-o', binary], cwd=source, env=child_env)
    (cache.parent / 'build.log').write_text(stdout + stderr)
    caches = list(cache.rglob('CMakeCache.txt'))
    targets = list(cache.rglob('target-goose_sqlite_native-*.json'))
    archives = list(cache.rglob('libgoose_sqlite_native.a'))
    if len(caches) != 1 or len(targets) != 1 or len(archives) != 1:
        raise RuntimeError('Expected one isolated production native build')
    values = {}
    for line in caches[0].read_text().splitlines():
        if line and not line.startswith(('#', '//')) and ':' in line.split('=', 1)[0] and '=' in line:
            key, value = line.split('=', 1)
            values[key.split(':', 1)[0]] = value
    if values['CMAKE_BUILD_TYPE'] != 'Release' or values['CMAKE_C_FLAGS_RELEASE'] != '-O3 -DNDEBUG' or values['CMAKE_C_FLAGS']:
        raise RuntimeError('Unexpected native optimization profile')
    identity, actual_compiler = compiler(values['CMAKE_C_COMPILER'])
    target = json.loads(targets[0].read_text())
    def include(path):
        actual = Path(path)
        if actual.is_relative_to(cache):
            return dict(path='$CACHE_INCLUDE',
                        headers={p.relative_to(actual).as_posix(): digest(p)
                                 for p in actual.rglob('*') if p.is_file()})
        return dict(path=path.replace(str(source), '$SNAPSHOT'))

    groups = [dict(language=g['language'],
                   flags=[f['fragment'] for f in g.get('compileCommandFragments', [])],
                   defines=[v['define'] for v in g.get('defines', [])],
                   includes=[include(v['path']) for v in g.get('includes', [])])
              for g in target['compileGroups']]
    generated = list((cache / 'build/prog').rglob('runner.c'))
    if len(generated) != 1:
        raise RuntimeError('Expected one generated Goose runner source')
    return dict(build_type=values['CMAKE_BUILD_TYPE'], compiler=identity, compile_groups=groups,
                native_archive_sha256=digest(archives[0]), generated_runner_sha256=digest(generated[0]),
                binary_sha256=digest(binary)), actual_compiler


def sqlite_identity(library):
    loaded = ctypes.CDLL(str(library))
    for name in ('sqlite3_libversion', 'sqlite3_sourceid'):
        getattr(loaded, name).restype = ctypes.c_char_p
        getattr(loaded, name).argtypes = []
    loaded.sqlite3_compileoption_get.restype = ctypes.c_char_p
    loaded.sqlite3_compileoption_get.argtypes = [ctypes.c_int]
    options = []
    for i in range(10000):
        value = loaded.sqlite3_compileoption_get(i)
        if value is None:
            break
        options.append(value.decode())
    else:
        raise RuntimeError('SQLite option enumeration exceeded defensive cap')
    return dict(version=loaded.sqlite3_libversion().decode(), source_id=loaded.sqlite3_sourceid().decode(),
                compile_options=options)


def counts(mode, size, n):
    operations = n * 1024 if mode == 'scan' else n
    expected = n * (n - 1) // 2 if mode == 'scalar' else operations * size if mode in ('text', 'blob', 'scan', 'lookup', 'batch') else n
    return operations, expected


def fixture(mode, size, iterations):
    n = max(1, iterations // 1024) if mode == 'scan' else max(1, iterations // 10) if size >= 65536 else iterations
    return n, *counts(mode, size, n)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--goose', required=True)
    parser.add_argument('--before-ref', required=True)
    parser.add_argument('--after-ref', required=True)
    parser.add_argument('--iterations', type=int, default=100000)
    parser.add_argument('--runs', type=int, default=9)
    parser.add_argument('--cpu', type=int)
    parser.add_argument('--output', type=Path, default=Path('.build/paired-results'))
    args = parser.parse_args()
    if not 1 <= args.iterations <= 10000000 or not 1 <= args.runs <= 100:
        parser.error('iterations/runs outside range')
    if args.cpu is not None:
        os.sched_setaffinity(0, {args.cpu})
    commits = {label: revision(value) for label, value in (('before', args.before_ref), ('after', args.after_ref))}
    dest = args.output if args.output.is_absolute() else ROOT / args.output
    if dest.exists() and any(dest.iterdir()):
        parser.error('Output directory must be empty; existing records are never overwritten')
    dest.mkdir(parents=True, exist_ok=True)
    (ROOT / '.build').mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='sqlite-paired-', dir=ROOT / '.build'))
    goose = Path(args.goose).resolve(strict=True)
    replacements = ((str(directory), '$BUILD'), (str(goose), '$GOOSE'), (str(ROOT), '$REPO'))

    def normalise(value):
        if isinstance(value, str):
            for old, new in replacements:
                value = value.replace(old, new)
            return value
        if isinstance(value, list):
            return [normalise(v) for v in value]
        if isinstance(value, dict):
            return {k: normalise(v) for k, v in value.items()}
        return value

    def write(name, value):
        (dest / name).write_text(json.dumps(normalise(value), indent=2) + '\n')

    harness_paths = (Path(__file__).resolve(), Path(__file__).with_name('measure.py').resolve())
    harness_hashes = {str(p.relative_to(ROOT)): digest(p) for p in harness_paths}
    env = os.environ.copy()
    cleared = ('CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'CC', 'CXX', 'CMAKE_GENERATOR',
               'CMAKE_TOOLCHAIN_FILE', 'CMAKE_PREFIX_PATH', 'CMAKE_C_COMPILER_LAUNCHER')
    for name in cleared:
        env.pop(name, None)
    metadata = dict(parent_started_utc_ns=time.time_ns(), refs=commits, iterations=args.iterations,
                    runs=args.runs, order_seed=SEED, affinity=sorted(os.sched_getaffinity(0)),
                    harness_source_commit=git('rev-parse', 'HEAD').decode().strip(), harness_hashes=harness_hashes,
                    harness_dirty=bool(git('status', '--porcelain', '--', *harness_hashes).strip()),
                    os=platform.platform(), cpu_model=next((v.split(':', 1)[1].strip() for v in Path('/proc/cpuinfo').read_text().splitlines() if v.startswith('model name')), ''),
                    governor={str(cpu): (Path(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor').read_text().strip()
                                         if Path(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor').exists() else None)
                              for cpu in os.sched_getaffinity(0)},
                    load_before=list(os.getloadavg()), snapshots={}, builds={}, cleared_build_environment=list(cleared),
                    build_command=['$GOOSE', 'build', 'bench/alternatives/runner.goose', '--cc', 'gcc', '-O2', '-o', '$BINARY'],
                    scope='Ten unchanged checked native Goose API paths. Frozen commits, isolated caches, balanced shuffled AB/BA pairs. Loop clocks exclude setup; GNU time whole-process RSS/wall/CPU include startup, setup, verification and launcher overhead. Shared host; no exclusive-core, universal-speedup or incremental-memory claim.')
    write('metadata.json', metadata)
    phase = dict(phase='build')
    samples = []
    journal = dest / 'samples.jsonl'
    journal.write_text('')
    try:
        version, _ = run([goose, '--version'])
        metadata['goose'] = dict(file=goose.name, version=version.strip(), sha256=digest(goose))
        binaries = {}
        compiler_files = {}
        for label, commit in commits.items():
            phase = dict(phase='build', implementation=label, commit=commit)
            source = directory / label / 'source'
            record = snapshot(commit, source)
            metadata['snapshots'][label] = record
            declared = (source / 'GOOSE_REVISION').read_text().strip()
            reported = re.match(r'goose ([0-9a-f]{7,40})(?:\s|$)', version)
            if reported is None or not declared.startswith(reported[1]):
                raise RuntimeError('Goose version does not match the declared compiler pin')
            record['goose_revision'] = declared
            binaries[label] = directory / label / 'runner'
            metadata['builds'][label], compiler_files[label] = build(source, directory / label / 'cache', binaries[label], goose, env)
            write('metadata.json', metadata)
        if metadata['snapshots']['before']['goose_revision'] != metadata['snapshots']['after']['goose_revision']:
            raise RuntimeError('Compiler pins differ')
        runner = 'bench/alternatives/runner.goose'
        if metadata['snapshots']['before']['source_hashes'][runner] != metadata['snapshots']['after']['source_hashes'][runner]:
            raise RuntimeError('Before/after fixture runners differ')
        for field in ('compiler', 'compile_groups', 'build_type'):
            if metadata['builds']['before'][field] != metadata['builds']['after'][field]:
                raise RuntimeError(f'Native build settings differ: {field}')
        libraries = {name: engine(path) for name, path in binaries.items()}
        if libraries['before'] != libraries['after']:
            raise RuntimeError('Actual shared SQLite objects differ')
        links = subprocess.check_output(['ldd', str(binaries['before'])], text=True)
        library = Path(next(line.split('=>', 1)[1].split('(', 1)[0].strip() for line in links.splitlines() if 'libsqlite3' in line and '=>' in line)).resolve()
        metadata['sqlite_libraries'] = libraries
        metadata['sqlite_identity'] = sqlite_identity(library)
        tools = {}
        for name in ('gcc', 'cmake', '/usr/bin/time'):
            identity, path = compiler(name)
            metadata.setdefault('tools', {})[identity['file']] = identity
            tools[name] = path, identity['sha256']
        if metadata['builds']['before']['compiler']['sha256'] != tools['gcc'][1]:
            raise RuntimeError('Native compiler does not match the requested gcc')
        metadata['rss_measurement'] = 'GNU time %M: benchmark-child whole-lifetime peak KiB; small native pre-exec footprint may remain; no Python-parent RSS floor'
        metadata['pairs'] = []
        write('metadata.json', metadata)
        rng = random.Random(SEED)
        for mode, size in FIXTURES:
            n, operations, expected = fixture(mode, size, args.iterations)
            warm_n = 1 if mode == 'scan' else 10
            _, warm_expected = counts(mode, size, warm_n)
            for label, binary in binaries.items():
                phase = dict(phase='warmup', implementation=label, fixture=mode, bytes=size)
                text, diagnostics = run([binary, warm_n, mode, size], env=env)
                elapsed, checksum = map(int, text.split())
                if diagnostics or elapsed <= 0 or checksum != warm_expected:
                    raise RuntimeError(f'Invalid warmup: {text}\n{diagnostics}')
            first = rng.randrange(2)
            orders = [(['before', 'after'] if (i + first) % 2 == 0 else ['after', 'before']) for i in range(args.runs)]
            rng.shuffle(orders)
            for repeat, order in enumerate(orders):
                pair = {}
                for position, label in enumerate(order):
                    phase = dict(phase='sample', implementation=label, fixture=mode, bytes=size,
                                 iterations=n, operations=operations, run=repeat, order=position)
                    rss = directory / 'rss.txt'
                    before = resource.getrusage(resource.RUSAGE_CHILDREN)
                    started_utc_ns = time.time_ns()
                    started = time.perf_counter_ns()
                    text, diagnostics = run(['/usr/bin/time', '-o', rss, '-f', '%M', '--', binaries[label], n, mode, size], env=env)
                    whole_wall = time.perf_counter_ns() - started
                    ended_utc_ns = time.time_ns()
                    after = resource.getrusage(resource.RUSAGE_CHILDREN)
                    elapsed, checksum = map(int, text.split())
                    peak = int(rss.read_text().strip())
                    if diagnostics or elapsed <= 0 or checksum != expected or peak < 0:
                        raise RuntimeError(f'Invalid measured result: {text}\n{diagnostics}')
                    sample = dict(phase, commit=commits[label], command=[f'${label.upper()}_BINARY', str(n), mode, str(size)],
                                  loop_wall_ns=elapsed, checksum=checksum, peak_rss_kib=peak,
                                  whole_wall_ns=whole_wall, whole_start_utc_ns=started_utc_ns, whole_end_utc_ns=ended_utc_ns,
                                  whole_cpu_ns=round((after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime) * 1e9))
                    samples.append(sample)
                    with journal.open('a') as stream:
                        stream.write(json.dumps(sample) + '\n')
                    pair[label] = elapsed
                metadata['pairs'].append(dict(fixture=mode, bytes=size, run=repeat, order=order,
                                              before_loop_ns=pair['before'], after_loop_ns=pair['after'],
                                              before_after_ratio=pair['before'] / pair['after']))
        phase = dict(phase='final verification')
        for label, record in metadata['snapshots'].items():
            verify_snapshot(directory / label / 'source', record)
            if engine(binaries[label]) != libraries[label] or digest(binaries[label]) != metadata['builds'][label]['binary_sha256']:
                raise RuntimeError('Measured binary or engine changed')
            if digest(compiler_files[label]) != metadata['builds'][label]['compiler']['sha256']:
                raise RuntimeError('Native compiler changed')
        if any(digest(path) != sha for path, sha in tools.values()) or digest(goose) != metadata['goose']['sha256']:
            raise RuntimeError('Measurement tool changed')
        if any(digest(ROOT / name) != sha for name, sha in harness_hashes.items()):
            raise RuntimeError('Harness changed during measurement')
        metadata.update(parent_completed_utc_ns=time.time_ns(), load_after=list(os.getloadavg()), samples=samples,
                        complete=True, sample_count=len(samples))
        write('samples.json', metadata)
        write('metadata.json', {k: v for k, v in metadata.items() if k != 'samples'})
        print(f'Recorded {len(samples)} checked paired samples in {dest}')
    except BaseException as error:
        write('failure.json', dict(phase, error_type=type(error).__name__, error=str(error),
                                   checked_samples=len(samples), timestamp_utc_ns=time.time_ns()))
        write('metadata.json', dict(metadata, complete=False))
        raise


if __name__ == '__main__':
    main()
