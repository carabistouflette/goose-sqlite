#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Checked file-backed Python API path; see CONTRACT.md for measurement scope."""
import sqlite3
import sys
import time

PAYLOAD = b'\x00' + b'x' * 126 + b'\xff'
INSERT = 'INSERT INTO items VALUES(?1,?2)'
if sys.flags.optimize:
    raise RuntimeError('Benchmark requires enabled assertions; use Python -I without -O')


def opened(path):
    db = sqlite3.connect(path, isolation_level=None, timeout=0, cached_statements=128)
    for sql in ('PRAGMA synchronous=FULL', 'PRAGMA cache_size=-2000',
                'PRAGMA foreign_keys=ON', 'PRAGMA trusted_schema=OFF',
                'PRAGMA locking_mode=NORMAL', 'PRAGMA wal_autocheckpoint=1000'):
        db.execute(sql).fetchall()
    keys = ('journal_mode', 'synchronous', 'page_size', 'cache_size',
            'wal_autocheckpoint', 'foreign_keys', 'trusted_schema', 'locking_mode', 'busy_timeout')
    policy = [db.execute('PRAGMA ' + key).fetchone()[0] for key in keys]
    assert policy[0] in ('delete', 'wal')
    assert policy[1:] == [2, 4096, -2000, 1000, 1, 0, 'normal', 0]
    return db, policy


def insert(cursor, id):
    cursor.execute(INSERT, (id, PAYLOAD))
    assert cursor.rowcount == 1 and cursor.description is None


def main():
    assert len(sys.argv) == 5
    path, mode = sys.argv[1:3]
    n, batch = map(int, sys.argv[3:])
    assert mode in ('commit', 'rollback', 'busy')
    assert 1 <= n <= 10000 and 1 <= batch <= 1024 and n * batch <= 1000000
    db, policy = opened(path)
    cursor = db.cursor()
    db.execute('BEGIN IMMEDIATE')
    insert(cursor, -2)
    db.execute('ROLLBACK')
    for end in ('COMMIT', 'ROLLBACK'):
        db.execute('BEGIN IMMEDIATE')
        db.execute(end)
    blocker = None
    if mode == 'busy':
        blocker, held_policy = opened(path)
        assert held_policy == policy
        blocker.execute('BEGIN IMMEDIATE')
        assert blocker.execute('UPDATE items SET payload=zeroblob(128) WHERE id=-1').rowcount == 1
    latencies = [0] * n
    codes = [0] * n
    if mode == 'busy':
        start = time.perf_counter_ns()
        for t in range(n):
            txn_start = time.perf_counter_ns()
            try:
                db.execute('BEGIN IMMEDIATE')
            except sqlite3.OperationalError as error:
                code = error.sqlite_errorcode
                assert code & 255 == 5
            else:
                raise AssertionError('held writer did not reject BEGIN')
            assert not db.in_transaction
            latencies[t] = time.perf_counter_ns() - txn_start
            codes[t] = code
        elapsed = time.perf_counter_ns() - start
    else:
        finish = 'COMMIT' if mode == 'commit' else 'ROLLBACK'
        start = time.perf_counter_ns()
        for t in range(n):
            txn_start = time.perf_counter_ns()
            db.execute('BEGIN IMMEDIATE')
            for i in range(batch):
                insert(cursor, t * batch + i)
            db.execute(finish)
            latencies[t] = time.perf_counter_ns() - txn_start
        elapsed = time.perf_counter_ns() - start
    assert elapsed > 0 and all(value > 0 for value in latencies)
    if blocker is not None:
        blocker.execute('ROLLBACK')
        blocker.close()
        db.execute('BEGIN IMMEDIATE')
        insert(cursor, 0)
        db.execute('COMMIT')
    rows = n * batch if mode == 'commit' else 1 if mode == 'busy' else 0
    cursor.execute('SELECT id,payload FROM items ORDER BY id')
    checksum = 0
    for i in range(rows + 1):
        row = cursor.fetchone()
        assert row is not None and type(row[0]) is int and type(row[1]) is bytes
        assert row == (i - 1, PAYLOAD)
        checksum += row[0] + 2
    assert cursor.fetchone() is None
    cursor.close()
    db.close()
    print('policy', *policy)
    print(elapsed, checksum, n if mode == 'commit' else 0,
          n if mode == 'busy' else 0, n if mode == 'rollback' else 0)
    for latency, code in zip(latencies, codes):
        print(latency, code)


if __name__ == '__main__':
    main()
