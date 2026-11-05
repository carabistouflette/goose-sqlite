# Concurrent connection validation

`make test-native CC=gcc` / `CC=clang` runs tests/threads.c under ASan/UBSan.
`python3 scripts/test-wal-engine.py --sanitizer thread` separately instruments
the verified pinned SQLite engine and adapter with TSan. It first requires a
deliberately racy probe to exit 66 with the expected race diagnostic. Startup
failures, unexpected diagnostics and timeouts fail the run; there are no race
suppressions or silent retries. These are finite correctness tests, not timings.

Eight threads race the first wrapper use, across eight thread generations and
1024 connection cycles. Barriers publish live handles, reject another thread's
connection/statement/BLOB tokens, and keep their owners alive until those checks
finish. Owners then read their complete expected values and close successfully.
Successor threads reject prior-generation stale handles. All 3072 minted tokens
must be nonzero and unique. Ordinary ASan/UBSan runs also race SQLite's cold start.

Another 64 workers abandon explicit write transactions with live statements and
modified BLOBs. Their pthread-key destructors must release everything and roll
back every byte. A test-only SQLite function destructor re-enters the wrapper:
the old token must already be invalid, and a fresh connection must work and close.
Callback state is thread-local; autoextension registration/reset happens outside
concurrent work. Reopened private files verify the complete original BLOB.

On supported patched WAL engines, deterministic phases prove write contention
and read snapshot stability before four writers/four readers start. Each writer
commits 64 unique rows; readers compare every integer and all 32 payload bytes,
then recheck count/sum in the same transaction. The final oracle requires 256 rows,
their exact sum, and 32 further complete snapshots. BUSY retries belong to this
test application and restart its explicit transaction with checked rollback;
the library never retries statements. Other errors fail. System-engine WAL skips
are explicit; pinned-engine runs require positive WAL coverage.

## TSan engine initialization scope

The first fully instrumented cold-start attempts reported races inside pristine
SQLite 3.54.1: local Clang 23 reported the `sqlite3_initialize` isInit fast path,
and hosted Clang 18 reported `sqlite3MutexInit` method initialization. Original
diagnostics are retained with the validation results. They arise in the verified,
unmodified SQLite amalgamation and remain unresolved; they are not a passing
concurrent cold-start TSan result.
SQLite documents initialize as thread-safe and also recommends explicit
[initialization](https://sqlite.org/c3ref/initialize.html) for portability.

A [fresh engine-only reproduction](results/cold-start-2026-11-05/README.md)
now isolates this report from the adapter: five cold `sqlite3_initialize()`
and five cold `sqlite3_open_v2()` runs reproduced under both static and shared
linkage from one verified instrumented SQLite object. Twenty matched cases
passed after one explicit engine initialization before worker creation. The
report does not determine whether the initialization access is a C-level race
or a sanitizer modeling issue; no false-positive conclusion or production
workaround follows.

The maintained TSan invocation calls the production gq_initialize entry (exposed
as sqlite::initialize) on the main thread before creating workers. It directly
calls sqlite3_initialize without caching failures or adding a lock. It still races
the first-ever registry/key/token use and exercises the teardown/WAL phases with both
engine and adapter instrumented. The executable reports engine_preinitialized,
which the driver checks and records. It does not test concurrent SQLite cold
initialization under TSan. No engine source or production adapter is changed to
silence these reports. ASan/UBSan retains concurrent cold initialization.

[Current results](results/startup-checkpoints-2026-11-05/README.md) record the
production startup entry and checkpoint contention checks under TSan.
[Earlier results and original diagnostics](results/concurrency-recovery-2026-11-04/README.md)
retain the initial campaign and cold-engine reports.

Timeouts bound whole processes and WAL retry loops. Repeated successful runs do
not prove absence of races, memory bugs, or filesystem failures. Handles remain
thread-affine; this does not add a shared connection, pool, or cross-thread API.
