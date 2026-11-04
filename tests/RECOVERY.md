# Storage failure recovery tests

`make test-native CC=clang` (or gcc) runs scripts/test-recovery.py against the
separate tests/recovery.c executable. The pinned-engine validation runs it too,
so positive WAL coverage is maintained on CI even with an older system engine.
No fault hooks are compiled into the production library.

A single-threaded VFS shim forwards calls to the installed default filesystem.
Each trial creates fresh, closed fixtures in a private temporary directory. It
opens checked native database handles and arms injection only for the operation
under test: one explicit transaction with a prepared UPDATE, incremental writes
to four BLOBs followed by COMMIT, or bounded online backup into an existing file.
Each fixture contains four 32 KiB BLOBs and integer generation markers. Test-only
small caches force page spills, and phase accounting checks that faults actually
reach blob_write, rather than testing its later COMMIT alone.

For rollback journal and supported WAL engines, the driver enumerates separately:

- xWrite returning SQLITE_IOERR_WRITE or SQLITE_FULL;
- xSync returning SQLITE_IOERR_FSYNC;
- one-shot failures and persistent failures within the armed operation;
- process termination immediately before each write or sync callback;
- process termination immediately after a successful COMMIT/backup acknowledgement.

Enumeration advances until the terminal no-hit successful trial, with a defensive
10000-point cap. Every supported group must hit a fault. Unsupported WAL engines
are reported as explicit group skips. The maintained pinned engine supplies the
positive WAL paths with --require-wal, which rejects every skipped WAL group. Child timeouts, unexpected diagnostics, signals and exit
statuses fail the test. UBSan halts on error, and deliberate crashes require an
exact unbuffered marker/status pair.

After ordinary errors, injection is disabled, autocommit is inspected, explicit
rollback is performed if needed, and all handles are closed. Fresh raw connections
run integrity_check and verify all IDs, integer marker storage and every BLOB byte.
A successful operation requires the complete new generation. An error or an
unacknowledged crash may leave a complete old or new generation; mixed generations
or partial data always fail. Backup sources must remain unchanged. Recovery is
verified before a fresh checked transaction is allowed to write. A subsequent
transaction commits successfully without changing the logical values, followed by
another fresh verification. Normal workers also require SQLite memory accounting
to return to zero after shutdown. Stale destroyed handles are rejected.

A deliberate process crash skips cleanup. The parent waits for child termination
and starts a separate verification process. Acknowledged success must survive as
the complete new generation. A crash before acknowledgement has an old-or-new
atomicity oracle. The OS cache survives: **these are not power-loss tests**.
There is no torn-write, write-reordering, truncate/delete/SHM failure or real disk
capacity model. FULL is a simulated return from xWrite; the host disk is not filled.
These finite fixtures do not establish absence of every storage bug. The approach
follows SQLite's distinction between [I/O faults and crash testing](https://sqlite.org/testing.html).

Ignored .build/recovery-*.json and .jsonl files retain cutpoints, failure counts,
primary/extended return codes, generation outcomes and acknowledgements. These
are correctness records, not performance measurements.

[Retained validation records](results/recovery-2026-11-04/README.md) describe the
completed compiler/engine matrix, its source identities and remaining limits.
