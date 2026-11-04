# SPDX-License-Identifier: Apache-2.0
import sqlite3
import sys
import time

if len(sys.argv) == 2 and sys.argv[1] == 'identity':
    db = sqlite3.connect(':memory:')
    print(sqlite3.sqlite_version)
    print(db.execute('SELECT sqlite_source_id()').fetchone()[0])
    for row in db.execute('PRAGMA compile_options'): print(row[0])
    sys.exit()
n, mode, size = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
assert 0 < n <= 10000000 and 0 <= size <= 65536
db = sqlite3.connect(':memory:', isolation_level=None, cached_statements=0 if mode == 'prepare' else 128)
db.execute('PRAGMA busy_timeout=1000')
cursor = db.cursor()
checksum = 0
if mode == 'prepare':
    start = time.perf_counter_ns()
    for i in range(n):
        cursor.execute('SELECT 1')
        row = cursor.fetchone()
        assert row == (1,) and cursor.fetchone() is None
        checksum += row[0]
elif mode == 'scalar':
    cursor.execute('SELECT ?1', (-1,))
    assert cursor.fetchone() == (-1,) and cursor.fetchone() is None
    start = time.perf_counter_ns()
    for i in range(n):
        cursor.execute('SELECT ?1', (i,))
        row = cursor.fetchone()
        assert row == (i,) and cursor.fetchone() is None
        checksum += row[0]
elif mode in ('text', 'blob'):
    data = 'x' * size if mode == 'text' else b'x' * size
    cursor.execute('SELECT ?1', (data,))
    assert cursor.fetchone()[0] == data and cursor.fetchone() is None
    start = time.perf_counter_ns()
    for i in range(n):
        cursor.execute('SELECT ?1', (data,))
        row = cursor.fetchone()
        assert row[0] == data and cursor.fetchone() is None
        checksum += len(row[0])
elif mode in ('scan', 'lookup', 'batch'):
    assert size >= 2
    data = b'\x00' + b'x' * (size - 2) + b'\xff'
    db.execute('CREATE TABLE items(id INTEGER PRIMARY KEY,group_id INTEGER,payload BLOB)')
    db.execute('CREATE INDEX by_group ON items(group_id)')
    insert = 'INSERT INTO items VALUES(?1,?1%17,?2)'
    if mode != 'batch':
        db.execute('BEGIN')
        for i in range(1024): cursor.execute(insert, (i, data))
        db.execute('COMMIT')
    if mode == 'batch':
        db.execute('BEGIN'); cursor.execute(insert, (-1, data)); db.execute('ROLLBACK')
        start = time.perf_counter_ns(); db.execute('BEGIN')
        for i in range(n): cursor.execute(insert, (i, data))
        db.execute('COMMIT'); elapsed = time.perf_counter_ns() - start
        cursor.execute('SELECT id,group_id,payload FROM items ORDER BY id')
        for i in range(n): assert cursor.fetchone() == (i, i % 17, data)
        assert cursor.fetchone() is None
        checksum = n * size
    elif mode == 'scan':
        sql = 'SELECT id,payload FROM items ORDER BY id'
        cursor.execute(sql)
        for i in range(1024): assert cursor.fetchone() == (i, data)
        assert cursor.fetchone() is None
        start = time.perf_counter_ns()
        for _ in range(n):
            cursor.execute(sql)
            for i in range(1024):
                row = cursor.fetchone(); assert row == (i, data)
                checksum += len(row[1])
            assert cursor.fetchone() is None
        elapsed = time.perf_counter_ns() - start
    else:
        sql = 'SELECT id,payload FROM items WHERE id=?1'
        cursor.execute(sql, (-1,)); assert cursor.fetchone() is None
        start = time.perf_counter_ns()
        for i in range(n):
            wanted = (i * 17) % 1024
            cursor.execute(sql, (wanted,))
            row = cursor.fetchone(); assert row == (wanted, data)
            checksum += len(row[1]); assert cursor.fetchone() is None
        elapsed = time.perf_counter_ns() - start
else:
    assert mode == 'insert'
    db.execute('CREATE TABLE items(x INTEGER)')
    db.execute('BEGIN')
    cursor.execute('INSERT INTO items VALUES(?1)', (-1,))
    db.execute('ROLLBACK')
    start = time.perf_counter_ns()
    db.execute('BEGIN')
    for i in range(n): cursor.execute('INSERT INTO items VALUES(?1)', (i,))
    db.execute('COMMIT')
    elapsed = time.perf_counter_ns() - start
    assert db.execute('SELECT count(*), sum(x) FROM items').fetchone() == (n, n * (n - 1) // 2)
    checksum = n
if mode not in ('insert', 'scan', 'lookup', 'batch'): elapsed = time.perf_counter_ns() - start
cursor.close()
db.close()
print(elapsed, checksum)
