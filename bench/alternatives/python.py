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
    start = time.perf_counter_ns()
    for i in range(n):
        cursor.execute('SELECT ?1', (i,))
        row = cursor.fetchone()
        assert row == (i,) and cursor.fetchone() is None
        checksum += row[0]
elif mode in ('text', 'blob'):
    data = 'x' * size if mode == 'text' else b'x' * size
    start = time.perf_counter_ns()
    for i in range(n):
        cursor.execute('SELECT ?1', (data,))
        row = cursor.fetchone()
        assert row[0] == data and cursor.fetchone() is None
        checksum += len(row[0])
else:
    assert mode == 'insert'
    db.execute('CREATE TABLE items(x INTEGER)')
    start = time.perf_counter_ns()
    db.execute('BEGIN')
    for i in range(n): cursor.execute('INSERT INTO items VALUES(?1)', (i,))
    db.execute('COMMIT')
    elapsed = time.perf_counter_ns() - start
    assert db.execute('SELECT sum(x) FROM items').fetchone()[0] == n * (n - 1) // 2
    checksum = n
if mode != 'insert': elapsed = time.perf_counter_ns() - start
cursor.close()
db.close()
print(elapsed, checksum)
