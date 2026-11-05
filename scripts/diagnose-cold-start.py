#!/usr/bin/env python3
"""Record pristine engine-only TSan startup diagnostics, not a safety pass."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('pinned_engine', ROOT / 'scripts/test-wal-engine.py')
PIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIN)
FLAGS = ['-O1', '-g', '-fno-omit-frame-pointer', '-fsanitize=thread', '-std=c11']
MODES = ('initialize-cold', 'initialize-serial', 'open-cold', 'open-serial')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--cpus', help='Comma-separated allowed CPU numbers; affinity is nonexclusive')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.runs <= 20:
        parser.error('runs must be 1..20')
    if args.cpus:
        try:
            cpus = {int(value) for value in args.cpus.split(',')}
        except ValueError:
            parser.error('cpus must be comma-separated integers')
        if not cpus or not cpus <= os.sched_getaffinity(0):
            parser.error('Every requested CPU must be allowed')
        os.sched_setaffinity(0, cpus)
    output = args.output.resolve()
    if output.is_relative_to(ROOT) and not output.is_relative_to(ROOT / '.build'):
        parser.error('Output must be ignored .build or external')
    env = os.environ.copy()
    if any(env.get(key) for key in ('LD_PRELOAD', 'LD_AUDIT', 'LD_LIBRARY_PATH')):
        parser.error('Unset loader overrides before diagnostic recording')
    output.mkdir(parents=True, exist_ok=False)
    compiler = Path(shutil.which(args.cc) or args.cc).resolve(strict=True)
    env['TSAN_OPTIONS'] = 'halt_on_error=1:exitcode=66'
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
    source_names = ('scripts/diagnose-cold-start.py', 'scripts/test-wal-engine.py',
                    'tests/cold-start.c', 'tests/tsan-probe.c')
    sources = {name: sha(ROOT / name) for name in source_names}
    metadata = dict(complete=False, safety_claim=False, source_commit=head, source_dirty=bool(dirty),
                    source_hashes=sources, compiler_sha256=sha(compiler), flags=FLAGS,
                    architecture=platform.machine(), cpus=sorted(os.sched_getaffinity(0)),
                    started_utc_ns=time.time_ns(), runs=args.runs, records=[], commands=[],
                    scope='Raw SQLite startup only; no wrapper or Goose code. Retain races and negatives. '
                          'A race report is not classified as benign; preinitialized success is not cold-start safety.')

    def normalize(text):
        return text.replace(str(output), '<build>').replace(str(ROOT), '<checkout>')

    def save():
        (output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')

    def run(command, label, timeout=180):
        command = [str(value) for value in command]
        process = subprocess.Popen(command, cwd=output, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        raw = stdout + stderr
        retained = normalize(raw.decode('utf-8', errors='replace')).encode()
        (output / (label + '.log')).write_bytes(retained)
        metadata['commands'].append(dict(label=label, argv=[normalize(v) for v in command],
            exit=process.returncode, timed_out=timed_out, raw_sha256=hashlib.sha256(raw).hexdigest(),
            retained_sha256=hashlib.sha256(retained).hexdigest()))
        save()
        if timed_out:
            raise RuntimeError(label + ' timed out; not a negative result')
        return process.returncode, stdout.decode(), stderr.decode()

    def checked(command, label):
        code, stdout, stderr = run(command, label)
        if code:
            raise RuntimeError(label + ' failed; see retained log')
        return stdout, stderr

    save()
    try:
        metadata['compiler_version'] = checked([compiler, '--version'], 'compiler')[0]
        with urllib.request.urlopen(PIN.URL, timeout=45) as response:
            archive = response.read(8 * 1024 * 1024 + 1)
        if len(archive) > 8 * 1024 * 1024 or hashlib.sha256(archive).hexdigest() != PIN.ARCHIVE_SHA256:
            raise RuntimeError('Pinned archive mismatch')
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            for name in ('sqlite3.c', 'sqlite3.h'):
                (output / name).write_bytes(zipped.read('sqlite-amalgamation-3540100/' + name))
        if hashlib.sha3_256((output / 'sqlite3.c').read_bytes()).hexdigest() != PIN.SOURCE_SHA3:
            raise RuntimeError('Pinned source mismatch')
        metadata['engine_source'] = dict(url=PIN.URL, archive_sha256=PIN.ARCHIVE_SHA256,
            source_sha3_256=PIN.SOURCE_SHA3, header_sha256=sha(output / 'sqlite3.h'))
        for name in ('tests/cold-start.c', 'tests/tsan-probe.c'):
            shutil.copyfile(ROOT / name, output / Path(name).name)
        checked([compiler, *FLAGS, 'tsan-probe.c', '-pthread', '-o', 'probe'], 'build-probe')
        code, _, stderr = run([output / 'probe'], 'positive-control', 20)
        if code != 66 or 'WARNING: ThreadSanitizer: data race' not in stderr:
            raise RuntimeError('Intentional race control failed; runtime unsupported or broken')
        checked([compiler, *FLAGS, '-fPIC', '-DSQLITE_THREADSAFE=1',
                 '-DSQLITE_DEFAULT_WAL_SYNCHRONOUS=1', '-c', 'sqlite3.c', '-o', 'sqlite3.o'], 'build-engine')
        checked([compiler, '-shared', '-fsanitize=thread', 'sqlite3.o',
                 '-Wl,-soname,libsqlite3.so.0', '-pthread', '-ldl', '-lm', '-o', 'libsqlite3.so.0'], 'link-shared')
        for linkage in ('static', 'shared'):
            linked = 'sqlite3.o' if linkage == 'static' else 'libsqlite3.so.0'
            checked([compiler, *FLAGS, '-I.', 'cold-start.c', linked,
                     '-pthread', '-ldl', '-lm', '-o', linkage], 'build-' + linkage)
        env['LD_LIBRARY_PATH'] = str(output)
        for linkage in ('static', 'shared'):
            linkage_text = checked(['ldd', output / linkage], 'ldd-' + linkage)[0]
            if linkage == 'shared' and str(output / 'libsqlite3.so.0') not in linkage_text:
                raise RuntimeError('Shared driver loaded wrong engine')
            if linkage == 'static' and 'libsqlite3.so' in linkage_text:
                raise RuntimeError('Static driver unexpectedly links a shared SQLite')
            for mode in MODES:
                for repeat in range(args.runs):
                    code, stdout, stderr = run([output / linkage, mode], f'{linkage}-{mode}-{repeat}', 20)
                    race = code == 66 and 'WARNING: ThreadSanitizer: data race' in stderr
                    clean = False
                    if code == 0 and not stderr:
                        result = json.loads(stdout)
                        clean = (result['mode'] == mode and result['workers'] == result['successes'] == 8
                                 and result['version'] == '3.54.1')
                    record = dict(linkage=linkage, mode=mode, run=repeat, exit=code,
                                  race_reported=race, clean=clean)
                    metadata['records'].append(record)
                    save()
                    if not (race or clean) or ('serial' in mode and not clean):
                        raise RuntimeError('Unexpected diagnostic/control outcome; no negative inference')
        metadata['artifact_hashes'] = {name: sha(output / name) for name in
            ('sqlite3.c', 'sqlite3.h', 'sqlite3.o', 'libsqlite3.so.0', 'cold-start.c', 'tsan-probe.c', 'static', 'shared', 'probe')}
        if sources != {name: sha(ROOT / name) for name in source_names} or sha(compiler) != metadata['compiler_sha256']:
            raise RuntimeError('Source/compiler changed during recording')
        if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() != head or subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True) != dirty:
            raise RuntimeError('Checkout changed during recording')
        metadata['complete'] = True
        metadata['completed_utc_ns'] = time.time_ns()
    except BaseException as error:
        metadata['failure'] = str(error)
        raise
    finally:
        save()
    print('Diagnostic recording complete; this is not a passing cold-start safety result.')


if __name__ == '__main__':
    main()
