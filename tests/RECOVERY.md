# Storage failure recovery tests

`make test-native CC=clang` (or gcc) runs scripts/test-recovery.py against the
separate tests/recovery.c executable. The pinned-engine validation runs it too,
so positive WAL coverage is maintained on CI even with an older system engine.
No fault hooks are compiled into the production library.

A single-threaded VFS shim forwards calls to the installed default filesystem.
Each trial creates fresh, closed fixtures in a private temporary directory. It
opens checked native database handles and arms injection only for the operation
under test: one explicit transaction with a prepared UPDATE, incremental writes
to four BLOBs followed by COMMIT, bounded online backup into an existing file, or
a WAL-only `checkpoint(TRUNCATE)` of already committed data.
Each fixture contains four 32 KiB BLOBs and integer generation markers. The old
backup destination also has a fully checked 64 KiB padding table, which makes it
larger than the replacement and forces truncation during rollback-journal backup.
Test-only small caches force page spills, mmap is disabled so reads pass through
xRead, and phase accounting checks that faults actually reach blob_write rather
than testing its later COMMIT alone. Test-only automatic WAL checkpoints are
disabled so the explicit checkpoint case starts with pending frames.

For rollback journal and supported WAL engines, the driver enumerates separately:

- xWrite returning SQLITE_IOERR_WRITE or SQLITE_FULL;
- xSync returning SQLITE_IOERR_FSYNC;
- xRead, xTruncate and xDelete returning their corresponding extended IOERR codes;
- xShmMap and xShmLock acquisitions returning SQLITE_IOERR_SHMMAP/SHMLOCK;
- one-shot failures and persistent failures within the armed operation;
- process termination immediately before each write or sync callback;
- process termination immediately after a successful COMMIT/backup/checkpoint
  acknowledgement.

Enumeration advances until the terminal no-hit successful trial, with a defensive
10000-point cap. Each supported write/FULL/sync/crash group must hit a fault.
For the added read/truncate/delete/SHM kinds, the method need not be called by
every workload: no-hit terminal trials are marked `unexercised` explicitly. Each
added kind must nevertheless have actual one-shot and persistent fault hits in
at least one of the original three workloads. SHM coverage is required only when
WAL is supported. The checkpoint scenario separately requires actual
write/FULL/sync/crash-write/crash-sync, truncate and SHM-lock coverage. Methods
not called by checkpoint, such as delete or SHM map, remain explicitly
unexercised; there is no claim that checkpoint exercises every VFS method.
Unsupported WAL engines are reported as explicit group skips. The maintained
pinned engine supplies the positive WAL paths with --require-wal, which rejects
every skipped WAL group. Child timeouts, unexpected diagnostics, signals and
exit statuses fail the test. UBSan halts on error, and deliberate crashes require an
exact unbuffered marker/status pair.

For COMMIT/BLOB/backup, after ordinary errors injection is disabled, autocommit
is inspected, explicit rollback is performed if needed, and all handles are
closed. Fresh raw connections
run integrity_check and verify all IDs, integer marker storage and every BLOB byte.
For backup, the old generation must retain the complete padding table and the
new generation must omit it; every padding byte is checked when present.
A successful operation requires the complete new generation. An error or an
unacknowledged crash may leave a complete old or new generation; mixed
generations or partial data always fail. Backup sources must remain unchanged. Recovery is
verified before a fresh checked transaction is allowed to write. A subsequent
transaction commits successfully without changing the logical values, followed by
another fresh verification. Normal workers also require SQLite memory accounting
to return to zero after shutdown. Stale destroyed handles are rejected.

The checkpoint case has a stronger oracle: it commits and fully verifies the
complete new generation **before** arming the checkpoint fault. Every checkpoint
error, unacknowledged crash and acknowledged crash must retain that new
generation; an old generation is always data loss. An idle anchor connection
keeps the WAL open so an implicit last-close checkpoint cannot substitute for
the API under test. After an ordinary error, fresh integrity and byte checks run
before closing/reopening the checked connection under the anchor. A subsequent
successful `checkpoint(TRUNCATE)` must report zero log/copied frames, followed
by another fresh full verification before any application write. The separate
crash-verification process opens its own anchor first and applies the same
verified checkpoint retry, then checks a fresh transaction and its final bytes.
The injected call's frame outputs and retry evidence are retained.

A deliberate process crash skips cleanup. The parent waits for child termination
and starts a separate verification process. Acknowledged success must survive as
the complete new generation. A crash before COMMIT/BLOB/backup acknowledgement
has an old-or-new atomicity oracle; checkpoint always requires the previously
committed new generation. The OS cache survives: **these are not power-loss tests**.
There is no torn-write, write-reordering, SHM-unlock/unmap or real disk capacity
model. SHM mapping failures return a null output, and read failures zero the output.
Lock releases are forwarded so injected acquisition failures cannot strand locks.
FULL is a simulated return from xWrite; the host disk is not filled.
These finite fixtures do not establish absence of every storage bug. The approach
follows SQLite's distinction between [I/O faults and crash testing](https://sqlite.org/testing.html).

Ignored .build/recovery-*.json and .jsonl files retain cutpoints, failure counts,
primary/extended return codes, generation outcomes and acknowledgements. These
are correctness records, not performance measurements.

[Expanded validation records](results/concurrency-recovery-2026-11-04/README.md)
describe the current compiler/engine matrix, source identities and remaining limits.
[Earlier records](results/recovery-2026-11-04/README.md) retain the historical
write/full/sync campaign and its narrower scope.
