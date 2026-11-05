#!/usr/bin/env python3
"""Record bounded pipe-coordinated WAL reader/writer implementation pairs."""
# SPDX-License-Identifier: Apache-2.0
import argparse
from collections import deque
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import random
import selectors
import shutil
import signal
import sqlite3
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('sqlite_filebacked_measure', ROOT / 'bench/filebacked/measure.py')
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
IMPLEMENTATIONS = BASE.IMPLEMENTATIONS
DEADLINE_SECONDS = 120
MAX_LINE = 4096
MAX_STDERR = 1024 * 1024


def source_hashes():
    paths = set(BASE.source_paths())
    paths.update(path for path in (ROOT / 'bench/mixedwal').rglob('*')
                 if path.is_file() and '__pycache__' not in path.parts and 'target' not in path.parts)
    for path in paths:
        if path.is_symlink():
            raise RuntimeError('Frozen sources must be regular files')
    return {path.relative_to(ROOT).as_posix(): BASE.digest(path) for path in sorted(paths)}


def payload(epoch, id):
    return bytes([0] + [(epoch * 17 + id * 31 + j * 7) % 256 for j in range(1, 127)] + [255])


def seed(path, rows):
    if path.exists():
        raise RuntimeError('Refusing to reuse a mixed database fixture')
    db = sqlite3.connect(path, isolation_level=None, timeout=0)
    try:
        db.execute('PRAGMA page_size=4096')
        if db.execute('PRAGMA journal_mode=wal').fetchone() != ('wal',):
            raise RuntimeError('Seed did not enter WAL')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE items(id INTEGER PRIMARY KEY,epoch INTEGER NOT NULL,payload BLOB NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        for id in range(rows):
            db.execute('INSERT INTO items VALUES(?,0,?)', (id, payload(0, id)))
        db.execute('COMMIT')
        if db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone() != (0, 0, 0):
            raise RuntimeError('Seed WAL did not truncate')
    finally:
        db.close()
    initial = BASE.files(path)
    if initial['wal'] is not None and initial['wal']['bytes'] != 0:
        raise RuntimeError('Seed WAL is not absent/empty')
    return initial


def anchor(path):
    db = sqlite3.connect(path, isolation_level=None, timeout=0)
    try:
        db.execute('PRAGMA synchronous=FULL')
        cursor = db.execute('SELECT id FROM items ORDER BY id')
        cursor.fetchall()
        cursor.close()
        if db.in_transaction:
            raise RuntimeError('Anchor must be idle')
    except BaseException:
        db.close()
        raise
    return db


def verify(path, rows, epoch):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0)
    logical = hashlib.sha256()
    try:
        if db.execute('PRAGMA journal_mode').fetchone() != ('wal',):
            raise RuntimeError('Journal changed during mixed workload')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise RuntimeError('Independent integrity check failed')
        cursor = db.execute('SELECT id,epoch,payload FROM items ORDER BY id')
        for id in range(rows):
            row = cursor.fetchone()
            expected = payload(epoch, id)
            if (row is None or type(row[0]) is not int or type(row[1]) is not int
                    or type(row[2]) is not bytes or row != (id, epoch, expected)):
                raise RuntimeError('Independent final epoch/payload oracle failed')
            logical.update(struct.pack('<qq', id, epoch) + expected)
        if cursor.fetchone() is not None:
            raise RuntimeError('Unexpected final row')
        cursor.close()
    finally:
        db.close()
    return dict(rows=rows, epoch=epoch, logical_sha256=logical.hexdigest(), integrity='ok')


def distribution(values):
    ordered = sorted(values)
    return dict(count=len(ordered), minimum=ordered[0] if ordered else None,
                maximum=ordered[-1] if ordered else None,
                nearest_rank_ns={label: ordered[math.ceil(fraction * len(ordered)) - 1] if ordered else None
                                 for label, fraction in (('p50', .5), ('p95', .95), ('p99', .99))})


class Pair:
    def __init__(self, runners, implementation, path, phase, attempts, rows, cap,
                 reader_cpu, writer_cpu, directory, env):
        self.directory = directory
        self.implementation = implementation
        self.attempts, self.rows, self.cap = attempts, rows, cap
        self.selector = selectors.DefaultSelector()
        self.pending = deque()
        self.children = {}
        self.streams = []
        self.buffers = {}
        self.eofs = set()
        self.stderr_bytes = {'reader': 0, 'writer': 0}
        self.event_index = 0
        self.deadline = time.monotonic() + DEADLINE_SECONDS
        self.started_ns = time.monotonic_ns()
        self.started_utc_ns = time.time_ns()
        self.events = (directory / 'events.jsonl').open('w')
        self.commands = {}
        try:
            for role, cpu in (('reader', reader_cpu), ('writer', writer_cpu)):
                command = ['/usr/bin/time', '-o', directory / (role + '-rss.txt'), '-f', '%M', '--',
                           'taskset', '-c', str(cpu), *runners[implementation], path, role, phase,
                           str(attempts), str(rows), str(cap)]
                self.commands[role] = [str(value) for value in command]
                process = subprocess.Popen(self.commands[role], cwd=ROOT, env=env, stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           start_new_session=True)
                self.children[role] = process
                # A broken actor must not block command writes past the pair deadline.
                os.set_blocking(process.stdin.fileno(), False)
                for kind, pipe in (('stdout', process.stdout), ('stderr', process.stderr)):
                    target = (directory / (role + '-' + kind + '.txt')).open('wb')
                    self.streams.append(target)
                    os.set_blocking(pipe.fileno(), False)
                    self.selector.register(pipe, selectors.EVENT_READ, (role, kind, target))
                    self.buffers[(role, kind)] = b''
        except BaseException:
            self.abort()
            self.close(suppress_errors=True)
            raise

    def event(self, direction, role, line):
        self.event_index += 1
        event = dict(sequence=self.event_index, direction=direction, role=role, line=line,
                     parent_monotonic_ns=time.monotonic_ns(), parent_utc_ns=time.time_ns())
        self.events.write(json.dumps(event) + '\n')
        self.events.flush()
        return event

    def send(self, role, command):
        process = self.children[role]
        if process.poll() is not None:
            raise RuntimeError('Cannot send to exited ' + role)
        event = self.event('send', role, command)
        process.stdin.write((command + '\n').encode('ascii'))
        process.stdin.flush()
        return event

    def pump(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Mixed pair exceeded 120-second deadline')
        for key, _ in self.selector.select(min(.2, remaining)):
            role, kind, target = key.data
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                self.selector.unregister(key.fileobj)
                self.eofs.add((role, kind))
                if self.buffers[(role, kind)]:
                    raise RuntimeError('Unterminated protocol line from ' + role)
                continue
            target.write(chunk)
            target.flush()
            if kind == 'stderr':
                self.stderr_bytes[role] += len(chunk)
                if self.stderr_bytes[role] > MAX_STDERR:
                    raise RuntimeError('Unbounded child stderr')
                continue
            value = self.buffers[(role, kind)] + chunk
            while b'\n' in value:
                line, value = value.split(b'\n', 1)
                if len(line) > MAX_LINE:
                    raise RuntimeError('Overlong child protocol line')
                event = self.event('receive', role, line.decode('ascii'))
                self.pending.append(event)
                if len(self.pending) > 4096:
                    raise RuntimeError('Unbounded pending child event queue')
            if len(value) > MAX_LINE:
                raise RuntimeError('Overlong partial child protocol line')
            self.buffers[(role, kind)] = value

    def receive(self, role, expected):
        while True:
            for index, event in enumerate(self.pending):
                if event['role'] == role:
                    del self.pending[index]
                    if event['line'] != expected:
                        raise RuntimeError(f'{role} expected {expected!r}, got {event["line"]!r}')
                    return event
            if (role, 'stdout') in self.eofs:
                raise RuntimeError('EOF before expected response from ' + role)
            self.pump()

    def ready(self):
        for role in ('reader', 'writer'):
            expected = 'policy inferred' if self.implementation == 'goose' else BASE.policy_expected('wal')
            self.receive(role, expected)
            self.receive(role, 'READY ' + role)
        if self.pending:
            raise RuntimeError('Unexpected event before start command')

    def finish(self):
        while len(self.eofs) != 4:
            self.pump()
        if self.pending:
            raise RuntimeError('Extra output after clean END')
        statuses, rss = {}, {}
        for role, process in self.children.items():
            remaining = max(.01, self.deadline - time.monotonic())
            statuses[role] = process.wait(timeout=remaining)
            if statuses[role] != 0:
                raise RuntimeError(role + ' exited unsuccessfully')
            rss[role] = int((self.directory / (role + '-rss.txt')).read_text().strip())
            if rss[role] < 0:
                raise RuntimeError('Negative child RSS')
        return dict(child_exit_status=statuses, role_peak_rss_kib=rss,
                    role_rss_scope='Separate whole-lifetime GNU time peaks, not simultaneous total memory; do not sum.',
                    pair_wall_ns=time.monotonic_ns() - self.started_ns,
                    pair_started_utc_ns=self.started_utc_ns, pair_completed_utc_ns=time.time_ns())

    def abort(self):
        for process in self.children.values():
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for process in self.children.values():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        # Preserve bytes already in the pipes even when protocol parsing or a
        # deadline failed before the other role/stream was drained.
        until = time.monotonic() + 1
        while self.selector.get_map() and time.monotonic() < until:
            for key, _ in self.selector.select(.05):
                role, kind, target = key.data
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    self.selector.unregister(key.fileobj)
                else:
                    target.write(chunk)
                    target.flush()

    def close(self, *, suppress_errors=False):
        errors = []
        def closing(resource):
            try:
                resource.close()
            except (OSError, ValueError) as error:
                errors.append(error)
        for process in self.children.values():
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    closing(pipe)
        closing(self.selector)
        for stream in self.streams:
            closing(stream)
        closing(self.events)
        if errors and not suppress_errors:
            raise errors[0]

    def qualification(self):
        self.ready()
        protocol = (('reader', 'H', 'HELD 0'), ('writer', 'C', 'COMMITTED 1'),
                    ('reader', 'V', 'VERIFIED 0'), ('reader', 'F', 'FRESH 1'),
                    ('writer', 'U', 'DIRTY 2'), ('reader', 'F', 'FRESH 1'),
                    ('writer', 'B', 'ROLLED_BACK 2'), ('reader', 'F', 'FRESH 1'))
        for role, command, expected in protocol:
            self.send(role, command)
            self.receive(role, expected)
        for role in ('reader', 'writer'):
            self.send(role, 'S')
        for role in ('reader', 'writer'):
            self.receive(role, 'END ' + role)
        return dict(qualification='held0/committed1/held0/fresh1/dirty2/fresh1/rollback2/fresh1',
                    final_epoch=1, **self.finish())

    def mixed(self, smoke):
        self.ready()
        states = {role: dict(started=False, done=False, ended=False, successes=0, busy=0,
                            window_ns=None, observations=[], previous_epoch=0)
                  for role in ('reader', 'writer')}
        self.observations = states
        self.send('reader', 'G')
        self.send('writer', 'G')
        stop = None
        writer_done = None
        while not all(state['ended'] for state in states.values()):
            if not self.pending:
                for role, state in states.items():
                    if (role, 'stdout') in self.eofs and not state['ended']:
                        raise RuntimeError('Unexpected stdout EOF from ' + role)
                self.pump()
                continue
            event = self.pending.popleft()
            role = event['role']
            state = states[role]
            fields = event['line'].split()
            if state['ended']:
                raise RuntimeError('Output after END')
            if fields == ['START', role] and not state['started']:
                state['started'] = True
                state['start_event'] = event
                continue
            if not state['started']:
                raise RuntimeError('Missing START before role output')
            letter = 'W' if role == 'writer' else 'R'
            if len(fields) == 5 and fields[0] == letter and not state['done']:
                if role == 'reader' and stop is not None:
                    raise RuntimeError('Reader operation after STOP')
                index, ns, code, epoch = map(int, fields[1:])
                if index != len(state['observations']) + 1 or ns <= 0 or code < 0 or (code != 0 and code & 255 != 5):
                    raise RuntimeError('Invalid role index/latency/SQLite code')
                limit = self.attempts if role == 'writer' else self.cap
                if index > limit:
                    raise RuntimeError('Role exceeded operation limit')
                if code == 0:
                    state['successes'] += 1
                    if role == 'writer' and epoch != state['successes']:
                        raise RuntimeError('Writer published epoch differs from successful commits')
                    if role == 'reader':
                        if not state['previous_epoch'] <= epoch <= self.attempts:
                            raise RuntimeError('Reader epoch decreased or exceeds attempt bound')
                        state['previous_epoch'] = epoch
                else:
                    state['busy'] += 1
                    expected = state['successes'] if role == 'writer' else -1
                    if epoch != expected:
                        raise RuntimeError('BUSY operation published an invalid epoch')
                state['observations'].append(dict(index=index, latency_ns=ns, sqlite_code=code,
                                                   epoch=epoch, receive_event=event))
                if role == 'reader':
                    stop = self.send('reader', 'S') if states['writer']['done'] else None
                    if stop is None:
                        self.send('reader', 'N')
                continue
            if len(fields) == 5 and fields[:2] == ['DONE', role] and not state['done']:
                window, successes, busy = map(int, fields[2:])
                if (window <= 0 or successes != state['successes'] or busy != state['busy']
                        or sum(row['latency_ns'] for row in state['observations']) > window):
                    raise RuntimeError('DONE role counts/window differ from observations')
                if role == 'writer' and len(state['observations']) != self.attempts:
                    raise RuntimeError('Writer did not complete all attempts')
                if role == 'reader' and stop is None:
                    raise RuntimeError('Reader DONE without parent STOP')
                state['done'], state['window_ns'], state['done_event'] = True, window, event
                if role == 'writer':
                    writer_done = event
                continue
            if fields == ['END', role] and state['done']:
                state['ended'] = True
                continue
            raise RuntimeError('Unexpected role protocol line: ' + event['line'])
        result = self.finish()
        commits = states['writer']['successes']
        observed = [row['epoch'] for row in states['reader']['observations'] if row['sqlite_code'] == 0]
        if any(epoch < 0 or epoch > commits for epoch in observed):
            raise RuntimeError('Reader observed an epoch outside final committed set')
        bands = sorted({(epoch - 1) * 4 // (commits - 1) for epoch in observed
                        if commits > 1 and 1 <= epoch < commits})
        minimum = max(8, math.ceil(.75 * self.attempts))
        gates = dict(minimum_commits=minimum, observed_commits=commits,
                     progress_bands=bands, required_bands=[0, 1, 2, 3],
                     coverage_required=not smoke, passed=commits >= minimum and bands == [0, 1, 2, 3])
        result.update(final_epoch=commits, gates=gates,
                      stop_dispatch_lag_ns=stop['parent_monotonic_ns'] - writer_done['parent_monotonic_ns'],
                      reader_done_lag_ns=states['reader']['done_event']['parent_monotonic_ns'] - writer_done['parent_monotonic_ns'],
                      stop_event=stop, writer_done_event=writer_done, roles=states)
        for role, state in states.items():
            success = [row['latency_ns'] for row in state['observations'] if row['sqlite_code'] == 0]
            errors = [row['latency_ns'] for row in state['observations'] if row['sqlite_code'] != 0]
            state['successful_latency'] = distribution(success)
            state['begin_busy_latency'] = distribution(errors)
            state['attempt_count'] = len(state['observations'])
            state['begin_busy_rate'] = state['busy'] / state['attempt_count'] if state['attempt_count'] else None
            state['successful_operations_per_second'] = state['successes'] * 1e9 / state['window_ns']
            state['rate_scope'] = ('Recorded writer loop commits/s, includes event logging' if role == 'writer'
                                   else 'COORDINATED snapshots/s, includes logging and per-snapshot parent wait')
        if commits < minimum or (not smoke and bands != [0, 1, 2, 3]):
            (self.directory / 'coverage-failure.json').write_text(json.dumps(result, indent=2) + '\n')
            raise RuntimeError('Writer commit floor or principal progress gate failed')
        return result


def execute_pair(runners, implementation, path, phase, attempts, rows, cap,
                 reader_cpu, writer_cpu, directory, env, smoke, normalize):
    directory.mkdir(parents=True, exist_ok=False)
    initial = seed(path, rows)
    held = anchor(path)
    pair = None
    try:
        pair = Pair(runners, implementation, path, phase, attempts, rows, cap,
                    reader_cpu, writer_cpu, directory, env)
        result = pair.qualification() if phase == 'qualify' else pair.mixed(smoke)
        result['initial_files'] = initial
        result['files_after_roles_before_verification'] = BASE.files(path)
        result['verified'] = verify(path, rows, result['final_epoch'])
        result['files_before_anchor_close'] = BASE.files(path)
        before = time.monotonic_ns()
        held.close()
        held = None
        result['anchor_cleanup_ns'] = time.monotonic_ns() - before
        result['files_after_anchor_close'] = BASE.files(path)
        result['commands'] = pair.commands
        pair.close()
        pair = None
        result['artifacts'] = {file.name: BASE.digest(file) for file in directory.iterdir()
                               if file.is_file() and file.name != 'result.json'}
        result = normalize(result)
        (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        for suffix in ('', '-wal', '-shm', '-journal'):
            Path(str(path) + suffix).unlink(missing_ok=True)
        return result
    except BaseException as error:
        if pair is not None:
            pair.abort()
            failure = dict(error=str(error), observed_roles=getattr(pair, 'observations', {}),
                           exit_status={role: process.poll() for role, process in pair.children.items()})
            pair.close(suppress_errors=True)
            (directory / 'failure.json').write_text(json.dumps(normalize(failure), indent=2) + '\n')
        raise
    finally:
        if held is not None:
            held.close()


def verify_builds(source, sources, output, runners, cpp, rustc, goose, metadata, head, dirty):
    if source_hashes() != sources or BASE.git('rev-parse', 'HEAD') != head or BASE.git('status', '--porcelain') != dirty:
        raise RuntimeError('Working source/HEAD/dirty state changed during recording')
    for name, value in sources.items():
        if BASE.digest(source / name) != value:
            raise RuntimeError('Frozen source changed during recording')
    for name, cmd in runners.items():
        if BASE.digest(cmd[0]) != metadata['binary_sha256'][name]:
            raise RuntimeError('Runner binary changed during recording')
        if name != 'python' and BASE.engine(cmd[0]) != metadata['sqlite_libraries'][name]:
            raise RuntimeError('Runner engine changed during recording')
    import _sqlite3
    if BASE.engine(_sqlite3.__file__) != metadata['sqlite_libraries']['python'] or BASE.digest(_sqlite3.__file__) != metadata['python']['extension_sha256']:
        raise RuntimeError('Python SQLite extension/engine changed')
    if BASE.engine(output / 'policy') != metadata['sqlite_libraries']['policy'] or BASE.digest(output / 'policy') != metadata['binary_sha256']['policy']:
        raise RuntimeError('Policy probe/engine changed')
    if BASE.digest(goose) != metadata['goose']['sha256'] or BASE.digest(rustc) != metadata['rustc']['sha256']:
        raise RuntimeError('Compiler changed')
    if BASE.git('-C', cpp, 'rev-parse', 'HEAD') != BASE.CPP_REV or BASE.git('-C', cpp, 'status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('SQLiteCpp checkout changed')
    for name, value in metadata['sqlitecpp_sources'].items():
        if BASE.digest(cpp / name) != value:
            raise RuntimeError('SQLiteCpp bytes changed')
    for name, identity in metadata['tools'].items():
        actual = Path(shutil.which(name) or name).resolve(strict=True)
        if BASE.digest(actual) != identity['sha256']:
            raise RuntimeError('Build/measurement tool changed')
    archives = list((output / 'goose-cache').rglob('libgoose_sqlite_native.a'))
    generated = list((output / 'goose-cache/build/prog').rglob('runner.c'))
    if (len(archives) != 1 or BASE.digest(archives[0]) != metadata['native_build']['archive_sha256']
            or len(generated) != 1 or BASE.digest(generated[0]) != metadata['native_build']['generated_caller_sha256']
            or BASE.digest(output / 'cpp-build/libSQLiteCpp.a') != metadata['sqlitecpp_build']['archive_sha256']):
        raise RuntimeError('Generated caller/native archive changed')


def cpu_topology(cpus):
    result = {}
    for cpu in sorted(set(cpus)):
        base = Path(f'/sys/devices/system/cpu/cpu{cpu}')
        fields = {}
        for name in ('physical_package_id', 'core_id', 'thread_siblings_list',
                     'core_siblings_list', 'core_type'):
            try:
                fields[name] = (base / 'topology' / name).read_text().strip()
            except OSError:
                fields[name] = None
        try:
            fields['cpu_capacity'] = (base / 'cpu_capacity').read_text().strip()
        except OSError:
            fields['cpu_capacity'] = None
        result[str(cpu)] = fields
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--goose', required=True, type=Path)
    parser.add_argument('--attempts', type=int, default=128)
    parser.add_argument('--rows', type=int, default=32)
    parser.add_argument('--read-cap', type=int, default=20000)
    parser.add_argument('--rounds', type=int, default=10)
    parser.add_argument('--writer-cpu', type=int)
    parser.add_argument('--reader-cpu', type=int)
    parser.add_argument('--coordinator-cpu', type=int)
    parser.add_argument('--engine-dir', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    if (not 8 <= args.attempts <= 4096 or not 1 <= args.rows <= 256
            or not 1 <= args.read_cap <= 100000 or (args.attempts + 1) * args.rows > 32768
            or not 2 <= args.rounds <= 100 or args.rounds % 2):
        parser.error('Bounds require attempts8..4096, rows1..256, read-cap1..100000, product<=32768 and even rounds2..100')
    if os.environ.get('LD_PRELOAD') or os.environ.get('LD_AUDIT'):
        parser.error('Loader preloads/audits are unsupported')
    engine_dir = args.engine_dir.resolve(strict=True) if args.engine_dir else None
    if engine_dir is None:
        if os.environ.get('LD_LIBRARY_PATH'):
            parser.error('Unset LD_LIBRARY_PATH or explicitly select the exact --engine-dir')
    elif os.environ.get('LD_LIBRARY_PATH') != str(engine_dir):
        parser.error('LD_LIBRARY_PATH must exactly equal the resolved --engine-dir')
    allowed = sorted(os.sched_getaffinity(0))
    if len(allowed) < 2:
        parser.error('Two allowed role CPUs are required')
    writer_cpu = args.writer_cpu if args.writer_cpu is not None else allowed[-2]
    reader_cpu = args.reader_cpu if args.reader_cpu is not None else allowed[-1]
    coordinator_cpu = args.coordinator_cpu if args.coordinator_cpu is not None else (allowed[-3] if len(allowed) >= 3 else allowed[0])
    if writer_cpu == reader_cpu or any(cpu not in allowed for cpu in (writer_cpu, reader_cpu, coordinator_cpu)):
        parser.error('Role CPUs must be distinct and every selected CPU originally allowed')
    if args.coordinator_cpu is not None and len(allowed) >= 3 and coordinator_cpu in (writer_cpu, reader_cpu):
        parser.error('Select a separate coordinator CPU where three are available')
    output, goose = args.output.resolve(), args.goose.resolve(strict=True)
    if output.is_relative_to(ROOT) and not output.is_relative_to(ROOT / '.build'):
        parser.error('Use an ignored .build output or an external directory')
    head, dirty = BASE.git('rev-parse', 'HEAD'), BASE.git('status', '--porcelain')
    if dirty and not args.smoke:
        parser.error('Principal recording requires clean committed source')
    sources = source_hashes()
    if not args.smoke:
        for name, value in sources.items():
            committed = subprocess.check_output(['git', 'show', head + ':' + name], cwd=ROOT)
            if hashlib.sha256(committed).hexdigest() != value:
                raise RuntimeError('Source differs from recorded Git blob: ' + name)
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'
    env, cleared = BASE.clean_environment()
    if engine_dir is not None:
        env['LD_LIBRARY_PATH'] = str(engine_dir)
    replacements = [(str(source), '$SOURCE'), (str(output), '$BUILD'), (str(goose), '$GOOSE'),
                    (str(goose.parent.parent), '$GOOSE_SOURCE')]
    if engine_dir is not None:
        replacements.append((str(engine_dir), '$ENGINE_DIR'))
    replacements.extend([(str(ROOT), '$REPO'), (str(Path.home()), '$HOME')])
    def normalize(value):
        if isinstance(value, Path):
            value = str(value)
        if isinstance(value, str):
            for old, new in replacements:
                value = value.replace(old, new)
            return value
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        return value
    os.sched_setaffinity(0, {coordinator_cpu})
    metadata = dict(source_commit=head, source_dirty=bool(dirty), source_hashes=sources,
                    complete=False, development_smoke=args.smoke, attempts=args.attempts,
                    rows=args.rows, read_cap=args.read_cap, rounds=args.rounds, order_seed=219,
                    expected_pair_count=len(IMPLEMENTATIONS) * args.rounds,
                    topology=dict(original_allowed=allowed, writer_cpu=writer_cpu,
                                  reader_cpu=reader_cpu, coordinator_cpu=coordinator_cpu,
                                  orientation='Swap writer/reader CPUs on odd rounds',
                                  hardware=cpu_topology((writer_cpu, reader_cpu, coordinator_cpu))),
                    governor={str(cpu): (Path(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor').read_text().strip()
                                         if Path(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_governor').exists() else None)
                              for cpu in set((writer_cpu, reader_cpu, coordinator_cpu))},
                    os=platform.platform(),
                    cpu_model=next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), ''),
                    load_before=list(os.getloadavg()), cleared_environment=cleared,
                    engine_override_directory=engine_dir,
                    parent_started_utc_ns=time.time_ns(), pair_count=0, qualifications=[],
                    scope='Bounded coordinated same-implementation reader/writer pairs; event logging and reader IPC waits affect role windows. Not identical offered load, isolated writer overhead, free-running saturation, exact continuous overlap, power-loss or exclusive-core evidence.',
                    retention='Successful databases/sidecars removed only after independent full oracle and hashes; all raw role streams/event journals retained. Failed fixtures retained, no automatic reruns.',
                    gates=dict(minimum_commits=max(8, math.ceil(.75 * args.attempts)),
                               required_intermediate_progress_bands=[0, 1, 2, 3],
                               deadline_seconds=DEADLINE_SECONDS, coverage_required=not args.smoke))
    def save():
        (output / 'metadata.json').write_text(json.dumps(normalize(metadata), indent=2) + '\n')
    save()
    samples = []
    try:
        for name, value in sources.items():
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
            if BASE.digest(target) != value:
                raise RuntimeError('Source changed while freezing')
        metadata['filesystem'] = json.loads(BASE.run(['findmnt', '-J', '-T', output], env=env)[0])
        if any(item['fstype'] in ('tmpfs', 'ramfs') for item in metadata['filesystem']['filesystems']):
            raise RuntimeError('Memory-backed fixture filesystem is unsupported')
        metadata['storage_scope'] = 'Warm OS cache; recorded mount is not proof of physical device/controller durability. Last-close anchor cleanup is outside role clocks.'
        runners, cpp, rustc = BASE.build_all(source, output, goose, env, metadata, save,
            goose_runner='bench/mixedwal/runner.goose', cpp_runner='bench/mixedwal/native.cpp',
            rust_binary_name='sqlite-mixedwal-bench', python_runner='bench/mixedwal/python.py')
        if engine_dir is not None and (engine_dir / 'evidence.json').is_file():
            evidence = engine_dir / 'evidence.json'
            record = json.loads(evidence.read_text())
            if record.get('engine_sha256') != metadata['sqlite_libraries']['goose']['sha256']:
                raise RuntimeError('Selected CI engine evidence differs from loaded object')
            metadata['selected_engine_evidence'] = dict(sha256=BASE.digest(evidence), content=record,
                                                        scope='Explicit selected-engine validation; not native performance evidence')
        policy_path = output / 'policy.db'
        metadata['policy_fixture_initial'] = seed(policy_path, args.rows)
        stdout, stderr = BASE.run([output / 'policy', policy_path], env=env)
        if stdout.strip() != BASE.policy_expected('wal') or stderr:
            raise RuntimeError('Goose policy inference probe differs from required WAL policy')
        metadata['policy_probe'] = dict(raw_stdout=stdout, raw_stderr=stderr,
            scope='Two simultaneous native connections with the same archive/options/engine; denial checked before test-only inspection. Actual Goose role policy is inferred, not queried through its permanent authorizer.')
        for suffix in ('', '-wal', '-shm', '-journal'):
            Path(str(policy_path) + suffix).unlink(missing_ok=True)
        save()
        for implementation in IMPLEMENTATIONS:
            directory = output / 'pairs' / ('qualify-' + implementation)
            metadata['active_pair'] = dict(implementation=implementation, phase='qualify', directory=directory)
            save()
            result = execute_pair(runners, implementation, directory / 'database.db', 'qualify',
                                  args.attempts, args.rows, args.read_cap, reader_cpu, writer_cpu,
                                  directory, env, args.smoke, normalize)
            metadata['qualifications'].append(dict(implementation=implementation, result=result))
            metadata.pop('active_pair', None)
            save()
        rng = random.Random(219)
        journal = output / 'samples.jsonl'
        journal.touch(exist_ok=False)
        for repeat in range(args.rounds):
            order = list(IMPLEMENTATIONS)
            rng.shuffle(order)
            wc, rc = (writer_cpu, reader_cpu) if repeat % 2 == 0 else (reader_cpu, writer_cpu)
            for position, implementation in enumerate(order):
                directory = output / 'pairs' / f'{repeat:02d}-{position}-{implementation}'
                context = dict(implementation=implementation, phase='mixed', run=repeat, order=position,
                               writer_cpu=wc, reader_cpu=rc, directory=directory)
                metadata['active_pair'] = context
                save()
                result = execute_pair(runners, implementation, directory / 'database.db', 'mixed',
                                      args.attempts, args.rows, args.read_cap, rc, wc, directory,
                                      env, args.smoke, normalize)
                record = normalize(dict(context, result=result))
                samples.append(record)
                with journal.open('a') as stream:
                    stream.write(json.dumps(record) + '\n')
                    stream.flush()
                metadata['pair_count'] = len(samples)
                metadata.pop('active_pair', None)
                save()
        verify_builds(source, sources, output, runners, cpp, rustc, goose, metadata, head, dirty)
        if len(samples) != metadata['expected_pair_count']:
            raise RuntimeError('Requested pair matrix incomplete')
        metadata['complete'] = True
        metadata['parent_completed_utc_ns'] = time.time_ns()
        metadata['load_after'] = list(os.getloadavg())
        (output / 'samples.json').write_text(json.dumps(normalize(dict(metadata, samples=samples)), indent=2) + '\n')
    except BaseException as error:
        metadata['failure'] = dict(error=str(error), active_pair=metadata.get('active_pair'))
        (output / 'failure.json').write_text(json.dumps(normalize(metadata['failure']), indent=2) + '\n')
        raise
    finally:
        save()
    print(f'Completed {len(samples)} coordinated pairs and {len(metadata["qualifications"])} qualifications')


if __name__ == '__main__':
    main()
