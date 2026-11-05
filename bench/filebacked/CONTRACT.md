# Runner contract

CLI: `runner PATH MODE TRANSACTIONS BATCH`, MODE commit/rollback/busy.
Bounds: transactions1..10000, batch1..1024, product<=1000000.
Private input file seeded with DELETE or WAL, page_size4096,
items(id INTEGER PRIMARY KEY,payload BLOB NOT NULL), single guard id=-1.
Payload128bytes: byte0=0, bytes1..126='x', byte127=255.

Open readwrite/privatecache/NOMUTEX where supported. Both connections use
busy_timeout0, synchronousFULL(2), cache_size=-2000, foreign_keysON,
trusted_schemaOFF, locking_modenormal, wal_autocheckpoint1000. Do not change
journal/page size. Read back policies OUTSIDE timing. Goose denies PRAGMA:
its settings are inferred from a separate test-only native probe linked to the
same archive/engine/options. No production bypass. Python exposes neither
NOMUTEX nor private-cache flags; preserve/disclose ordinary Python policy.

Prepare INSERT INTO items VALUES(?1,?2) once (Python uses its SQL cache).
On same connection before timing: BEGIN IMMEDIATE; insert id=-2 with payload,
require direct changes1; ROLLBACK. Then empty BEGIN IMMEDIATE/COMMIT and
BEGIN IMMEDIATE/ROLLBACK to prime control SQL caches. Prepare/exec control SQL
inside timing using each wrapper's normal interface, disclose different caching.
Every INSERT binds/copies input, consumes DONE/reset and checks direct changes1.

commit: N transactions, BEGIN IMMEDIATE; BATCH inserts id=t*BATCH+i; COMMIT.
rollback: same but ROLLBACK. Each per-transaction monotonic duration includes
BEGIN, inserts, changes checks and COMMIT/ROLLBACK. Outer loop clock also includes
latency recording/loop overhead. Timed outcomes commits=N,busy0,rollbacks0 for
commit; commits0,busy0,rollbacks=N for rollback.

busy: open second connection after priming with same settings/readback. Blocker:
BEGIN IMMEDIATE; UPDATE items SET payload=zeroblob(128) WHERE id=-1; changes1.
Primary N timed BEGIN IMMEDIATE attempts, all primary SQLITE_BUSY5 and autocommit
true, no automatic retries. Attempt duration includes error/finalize handling and
autocommit check. After loop clock stops, ROLLBACK/close blocker; SAME primary
BEGIN IMMEDIATE; insert id0 with payload, changes1; COMMIT. This untimed recovery
is mandatory. Timed outcomes commits0,busy=N,rollbacks0. This is controlled
rejection latency, NOT concurrent throughput/fairness or waiting-time behavior.
No threads, sleeps or racing release. Fail on unexpected errors.

After timing SELECT id,payload FROM items ORDER BY id, strict integer/blob types,
owned output, every byte exact. Expect guard then IDs0..N*BATCH-1 for commit;
guard only rollback; guard then id0 busy. Consume DONE/close cleanly.
Checksum=sum(id+2) including guard: commit1+k*(k+3)/2, rollback1,busy3.
Coordinator independently reopens after child exit and verifies all data/integrity.

stdout exactly: line1
`policy JOURNAL SYNC PAGE CACHE AUTOCHECKPOINT FOREIGNKEYS TRUSTEDSCHEMA LOCKING BUSYMS`
(or `policy inferred` only for Goose).
line2 `LOOP_NS CHECKSUM COMMITS BUSY ROLLBACKS`
then exactly N lines `NANOSECONDS SQLITE_CODE` (code0 after successful commit/rollback; actual SQLite error code after BUSY). No stdout until all
verification and close succeed. Diagnostics stderr, checks always enabled.
Every process/sample uses a fresh file; warmups use separate files. Coordinator
records filesystem/mount/storage scope and pre/post file/WAL sizes; no cache-drop
or power-loss guarantee. Policy matching does not equal identical API overhead.
