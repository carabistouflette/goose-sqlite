#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Pipe-coordinated checked WAL reader/writer path. See CONTRACT.md."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'filebacked'))
from python import opened  # noqa: E402

SELECT = 'SELECT id,epoch,payload FROM items ORDER BY id'
UPDATE = 'UPDATE items SET epoch=?1,payload=?2 WHERE id=?3'


def emit(*values):
    print(*values, flush=True)


def command():
    line = sys.stdin.readline(3)
    token = line[:-1] if line.endswith('\n') else line
    if len(token) != 1 or token not in 'HCVFUBSGN':
        raise RuntimeError('Malformed command or unexpected control EOF')
    return token


def main():
    assert len(sys.argv) == 7 and not sys.flags.optimize
    path, role, phase = sys.argv[1:4]
    attempts, rows, cap = map(int, sys.argv[4:])
    assert role in ('reader', 'writer') and phase in ('qualify', 'mixed')
    assert 8 <= attempts <= 4096 and 1 <= rows <= 256 and 1 <= cap <= 100000
    assert (attempts + 1) * rows <= 32768
    expected = [bytes([0] + [(epoch * 17 + id * 31 + j * 7) % 256
                            for j in range(1, 127)] + [255])
                for epoch in range(attempts + 1) for id in range(rows)]
    db, policy = opened(path)
    assert policy[0] == 'wal'
    query, update = db.cursor(), db.cursor()

    def scan():
        query.execute(SELECT)
        epoch = None
        for id in range(rows):
            row = query.fetchone()
            assert row is not None and type(row[0]) is int and type(row[1]) is int and type(row[2]) is bytes
            assert row[0] == id and 0 <= row[1] <= attempts
            if epoch is None:
                epoch = row[1]
            assert row[1] == epoch and row[2] == expected[epoch * rows + id]
        assert query.fetchone() is None
        return epoch

    def update_all(epoch):
        for id in range(rows):
            try:
                update.execute(UPDATE, (epoch, expected[epoch * rows + id], id))
            except Exception as error:
                raise RuntimeError(f'update stage code={getattr(error, "sqlite_errorcode", -1)}') from error
            assert update.rowcount == 1 and update.description is None

    def control(sql):
        try:
            db.execute(sql)
        except Exception as error:
            raise RuntimeError(f'{sql} stage code={getattr(error, "sqlite_errorcode", -1)}') from error

    def fresh():
        control('BEGIN DEFERRED')
        epoch = scan()
        control('COMMIT')
        return epoch

    if role == 'writer':
        control('BEGIN IMMEDIATE')
        update_all(0)
        control('ROLLBACK')
        for end in ('COMMIT', 'ROLLBACK'):
            control('BEGIN IMMEDIATE')
            control(end)
    else:
        assert fresh() == 0
    emit('policy', *policy)
    emit('READY', role)
    if phase == 'qualify':
        held = False
        sequence = 'H V F F F S'.split() if role == 'reader' else 'C U B S'.split()
        step = 0
        while True:
            c = command()
            assert step < len(sequence) and c == sequence[step]
            step += 1
            if c == 'S':
                assert not held and not db.in_transaction
                break
            if role == 'reader':
                if c == 'H':
                    assert not held
                    control('BEGIN DEFERRED')
                    assert scan() == 0
                    held = True
                    emit('HELD', 0)
                elif c == 'V':
                    assert held and scan() == 0
                    emit('VERIFIED', 0)
                elif c == 'F':
                    if held:
                        control('COMMIT')
                        held = False
                    assert fresh() == 1
                    emit('FRESH', 1)
                else:
                    raise RuntimeError('Invalid reader qualification command')
            else:
                if c in ('C', 'U'):
                    assert not db.in_transaction
                    control('BEGIN IMMEDIATE')
                    update_all(1 if c == 'C' else 2)
                    if c == 'C':
                        control('COMMIT')
                        emit('COMMITTED', 1)
                    else:
                        emit('DIRTY', 2)
                elif c == 'B':
                    assert db.in_transaction
                    control('ROLLBACK')
                    emit('ROLLED_BACK', 2)
                else:
                    raise RuntimeError('Invalid writer qualification command')
    else:
        assert command() == 'G'
        emit('START', role)
        successes = busy = 0
        start = time.perf_counter_ns()
        if role == 'writer':
            for i in range(1, attempts + 1):
                op = time.perf_counter_ns()
                code = 0
                try:
                    db.execute('BEGIN IMMEDIATE')
                except Exception as error:
                    code = getattr(error, 'sqlite_errorcode', -1)
                    assert code >= 0 and code & 255 == 5 and not db.in_transaction
                    busy += 1
                else:
                    update_all(successes + 1)
                    control('COMMIT')
                    successes += 1
                ns = time.perf_counter_ns() - op
                assert ns > 0
                emit('W', i, ns, code, successes)
        else:
            previous = 0
            for i in range(1, cap + 1):
                op = time.perf_counter_ns()
                code, epoch = 0, -1
                try:
                    db.execute('BEGIN DEFERRED')
                except Exception as error:
                    code = getattr(error, 'sqlite_errorcode', -1)
                    assert code >= 0 and code & 255 == 5 and not db.in_transaction
                    busy += 1
                else:
                    epoch = scan()
                    assert epoch >= previous
                    control('COMMIT')
                    previous = epoch
                    successes += 1
                ns = time.perf_counter_ns() - op
                assert ns > 0
                emit('R', i, ns, code, epoch)
                c = command()
                if c == 'S':
                    break
                assert c == 'N'
            else:
                raise RuntimeError('Reader operation cap exhausted before STOP')
        elapsed = time.perf_counter_ns() - start
        assert elapsed > 0 and not db.in_transaction
        emit('DONE', role, elapsed, successes, busy)
    query.close()
    update.close()
    db.close()
    emit('END', role)


if __name__ == '__main__':
    main()
