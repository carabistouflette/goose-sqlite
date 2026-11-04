# Interface

All functions are in namespace `sqlite`. Interface is experimental. Connections,
statements and BLOB handles are thread-affine, synchronous resources. Storage is owned by the
application or SQLite; no SQLite pointer is exposed.

## Results

Most functions return a signed `i64` code. `OK=0`, `ROW=100`, `DONE=101`.
Other nonnegative results are SQLite primary/extended codes. For a positive
error, `code & 255` is the primary code. For example 1555 is primary-key constraint
failure, primary 19. Test success against the documented exact success code;
`code >= 0` does not mean success.

Negative wrapper codes: `INVALID_INPUT=-1`, `INVALID_HANDLE=-2`,
`INVALID_STATE=-3`, `TYPE_MISMATCH=-4`, `LIMIT=-5`. They do not have their own
SQLite error messages. Wrapper validation that calls
SQLite (for example, rejecting a prepared SQL suffix) can replace earlier engine
error text, even when it returns a negative wrapper code.
`error_message(db,out)` copies the current SQLite message
(up to 4096 bytes), returning OK or a wrapper error. Copy it immediately after
an engine error and before another SQLite operation; it may describe a previous
engine operation after a wrapper error. Open failures have no live connection
and therefore no error-message handle; inspect their numeric result.

## Connections and statements

`Options { readonly=false, wal=false, busy_ms=1000, work_budget=1000000 }`.
`open(path,options) -> Database,code`. Path is 1..4095 bytes with no NUL or `file:`
prefix. `:memory:` opens a private in-memory database. Other paths use ordinary
SQLite file semantics; caller controls path trust and filesystem permissions.
Readonly uses SQLITE_OPEN_READONLY; writable opens/creates. Failed open returns
an invalid zero-token Database and closes partially initialized SQLite state.
No journal/synchronous/durability setting is weakened by this module.

`close(db) -> code`: returns SQLITE_BUSY (5) while statements or BLOB handles remain live. Busy
leaves the connection usable. Successful close invalidates all token copies and
rolls back open transactions according to SQLite close semantics.

`prepare(db,sql) -> Statement,code`: 1..65536 SQL bytes, no embedded NUL, exactly
one executable statement. Trailing whitespace and comments
are accepted, including block comments ending at EOF. SQLite decides the grammar
of the first statement, including leading empty statements. A second statement
or extra semicolon in the suffix, and empty/comment-only SQL, are rejected. SQL is trusted application code;
untrusted values must use parameters. Prepared statements use SQLite's persistent
preparation hint and can be reused. Failure returns a zero-token Statement.

`finalize(stmt) -> code`: destroys the statement even if returning its last engine
execution error. Every copy becomes stale. Finalizing early can finish/commit a
write that produced RETURNING rows; do not treat early cleanup as cancellation.

`reset(stmt) -> code`: restores Ready, preserving bindings, even when reporting
the previous execution error or a deferred failure. Check its return code.
`clear_bindings(stmt)` changes every binding to NULL, only in Ready.

`step(stmt)`: Ready/Row -> ROW or Done/Failed. ROW allows reading one row and
stepping again. Any other result requires reset before another step. This
includes SQLITE_BUSY: reset before retrying; there is no hidden retry or repeated
execution after DONE. An engine error may roll back its transaction; applications
must explicitly recover rather than assume the transaction remains open.

`column_count(stmt)` returns result-column count or INVALID_HANDLE, in any state.
`execute(db,sql)` prepares one statement, rejects any result columns before
stepping, then steps and finalizes. Returns OK on successful DONE/cleanup.
It performs no implicit transaction. Query/RETURNING rejection returns
INVALID_STATE. Use explicit `BEGIN`, `COMMIT`, `ROLLBACK` through execute.

## Binding and reading

Ready statements accept `bind_null(stmt,index)`, `bind_integer(stmt,index,i64)`,
`bind_float(stmt,index,f64)`, `bind_text(stmt,index,bytes)` and
`bind_blob(stmt,index,bytes)`. Parameter indices are one-based, up to the prepared
parameter count (at most 128). Unbound parameters are NULL. Bindings copy the
input using SQLITE_TRANSIENT; source storage can immediately change/disappear.
Float bindings reject NaN and infinity. Text/blob lengths are 0..1048576; embedded
NUL is preserved and empty bytes are not NULL. SQLite text uses UTF-8 conventions;
this module does not independently validate or normalize Unicode. Bind data as
blob when it is not text. Failed binding leaves subsequent state governed by
SQLite; rebind or clear explicitly before execution.

Only Row statements permit zero-based column reads:

- `column_type(stmt,column)`: INTEGER=1, FLOAT=2, TEXT=3, BLOB=4, NULL=5, or a
  negative wrapper code.
- `column_integer(stmt,column) -> value,code` and
  `column_float(stmt,column) -> value,code`: exact matching storage type, no
  implicit coercion. Value is zero on error. SQLite column affinity may change
  the stored type at insertion; inspect `column_type` if schema types vary.
- `column_text(stmt,column,out)` and `column_blob(stmt,column,out)`: replace a
  caller-owned growable byte array, empty on failure. Require exact storage type;
  NULL is TYPE_MISMATCH. Copies remain valid after stepping, reset or cleanup.

## Limits and policies

Per OS thread: 16 databases, 64 statements and 32 BLOB handles total. Allocation beyond a registry
limit returns LIMIT; finalizing/closing releases capacity. Tokens never repeat;
exhaustion fails closed. Thread exit finalizes live statements, closes BLOB handles, then closes
connections. Finalization can commit implicit RETURNING writes that already
produced rows; only transactions still open afterward, including uncommitted
explicit transactions, roll back on close. Cleanup is not a cancellation request.
Use explicit cleanup normally;
process abort/exit is not a substitute for orderly cleanup. Threads do not share
handles; each thread must open its own connection. The system SQLite must be
built thread-safe and must not be configured globally in single-thread mode.
This module does not configure SQLite globally.

SQL/value limits are input limits. SQLite also limits encoded row/value size to
1 MiB, columns/variables to 128, expression depth to 64, compound SELECT terms to
32, VDBE opcodes to 250000, trigger depth to 16, attached databases and helper
worker threads to zero. SQLite itself may impose tighter compile-time limits.
SQLite's row encoding overhead means a maximum-sized bound value may not fit
inside a stored row. Errors originate from SQLite when its limits are reached.

`busy_ms` accepts 0..30000. `work_budget` accepts 1000..100000000, with progress
checks about every 1000 VM instructions, reset separately before prepare and
step. Interrupt returns SQLITE_INTERRUPT (9). This does not bound total stream
work, elapsed time, filesystem I/O, native-function work, heap usage, disk growth,
or preparation work on older SQLite versions. Sorting/scanning a large database
may interrupt before producing its first row. SQLite 3.41+ improves progress
coverage during preparation. Applications must bound their own row/result loops.

Connections enable foreign keys and defensive mode, disable trusted schemas,
extension loading and double-quoted string literals, and use private caches.
An authorizer denies all PRAGMAs, ATTACH/DETACH and virtual table creation/deletion;
SQL cannot override these initial policies. Virtual tables and VACUUM are
unsupported; some SQLite features internally use denied operations. Files, SQL
and databases are not isolated from other trusted native libraries in the same
process. See SECURITY.md for trust assumptions and testing scope.

## Named parameters, metadata and connection status

`parameter_count(stmt)` reports SQLite's largest parameter index, in any live
statement state. Sparse `?5` reserves five slots, and repeated `:name` shares an
index. `parameter_index(stmt,name)` returns that one-based index, zero if absent,
or a negative wrapper error. Names must include their exact `:`, `@`, `$` or `?`
prefix, contain no NUL and be 1..1024 bytes; spelling/case are not normalized.
Bind the returned positive index through the existing typed bind functions.

`column_name(stmt,column,out)` copies a result name in any live statement state,
including before execution and after reset/DONE. Columns are zero-based; invalid
indices/handles clear output. Names are bounded to 65536 bytes, may be empty or
duplicate, and survive statement cleanup after copying. Use SQL aliases for
stable names; SQLite can rename generated expressions or reprepare statements.
Allocation failures return SQLITE_NOMEM, never a name-length disguised as status.

`changes(db) -> count,code` uses SQLite's 64-bit direct-DML counter, excluding
auxiliary trigger/foreign-key effects. It is not a committed-row receipt and can
retain a previous DML count across unrelated statements. `last_insert_rowid(db)
-> id,code` returns connection state: IDs may be negative, WITHOUT ROWID inserts
do not update it, and rollback does not restore its previous value.
`autocommit(db) -> enabled,code` queries the engine's actual autocommit mode.
Check it after errors: ordinary constraint failures can leave an explicit
transaction active, whereas INSERT OR ROLLBACK can end it. Scalar outputs are
zero/false on invalid handles; always check the accompanying status.

Explicit transactions and savepoints need no additional execution interface:
`execute(db,"BEGIN IMMEDIATE")`, `execute(db,"SAVEPOINT fixed_name")`,
`execute(db,"ROLLBACK TO fixed_name")`, `execute(db,"RELEASE fixed_name")` and
`execute(db,"COMMIT")` all report errors. ROLLBACK TO leaves the savepoint active;
RELEASE of an inner savepoint is not an independent commit. Use fixed/trusted
names, preserve the original operation or COMMIT error, and check recovery errors
separately. These operations are not destructor/RAII guards.

## WAL at connection creation

`Options.wal=true` requests WAL on the main file. The connection must be writable
and file-backed: readonly+wal is INVALID_INPUT; an in-memory mode fallback is
an error. Initialization verifies the actual journal mode and sets synchronous
at least FULL (preserving EXTRA), including on engines compiled with a weaker WAL
default. Arbitrary PRAGMAs remain denied throughout the public connection lifetime.
Failure returns a zero token and closes native state, but a journal-mode change
may already have persisted to the file; open is not a filesystem transaction.
The default `wal=false` preserves the engine/file journal mode.

SQLite's [WAL-reset corruption fix](https://sqlite.org/wal.html#walresetbug) is
required: recognized versions are 3.51.3+, 3.50.7..3.50.x, or 3.44.6..3.44.x.
Other versions return SQLITE_MISUSE (21) when WAL is requested or detected at
open, even if a distributor independently backported the fix. This conservative
check cannot police external connections switching the file to WAL later.
**Every participant must use an updated engine.** The minimum 3.37 supports
rollback-journal operations; it is not a WAL safety endorsement.

WAL permits snapshot readers alongside a writer, but does not permit multiple
simultaneous writers. All processes must be on one host with a suitable local
filesystem. Sidecar -wal/-shm files, directory permissions, checkpoints and busy
results follow SQLite. Readonly connections preserve existing WAL on recognized
fixed versions when the engine can open its sidecars. This library does not offer
manual checkpoints, journal-mode switching on a live handle, or weaker durability.

## Incremental BLOB access

`blob_open(db,table,column,rowid,writable) -> Blob,code` opens byte-oriented access
in the main schema. Table and column names are exact SQLite API strings, not SQL
fragments: 1..1024 bytes, no NUL. Rowid is signed. No pointer escapes. SQLite allows
TEXT or BLOB storage in supported ordinary rowid tables; it rejects NULL/scalars,
missing rows, views and virtual/WITHOUT ROWID tables. Tables with generated columns
are also rejected on newer SQLite versions; some older engines permit access to
ordinary columns in those tables. Writable indexed/primary/unique/foreign-key child columns, and some
expression-index tables, are rejected by the engine. Failed open has a zero token.
Values larger than 1 MiB are rejected and their partial handle is closed.

Writable access requires an explicit transaction (autocommit disabled), otherwise
INVALID_STATE. Use BEGIN, check all writes and close results, then COMMIT. A live
writable BLOB can make COMMIT return BUSY. ROLLBACK expires the handle; close it
and inspect errors before recovery. Close normally and do not rely on thread exit.

`blob_size(blob) -> size,code` probes validity and reports zero on failure.
`blob_read(blob,offset,count,out)` replaces owned output, empty on error.
`blob_write(blob,offset,bytes)` copies bytes synchronously into SQLite. Ranges must
fit the original value; offset/count cannot be negative, overflow, or extend it.
Reads accept count 0..1048576; empty access still asks SQLite to detect readonly
writes and expiration. Reads/writes do not resize the stored value. Use SQL
zeroblob to allocate it. Copied read buffers survive handle close/transaction end.

Updating/deleting the row (including an unrelated column), or rolling back, can
expire the handle. Further accesses return SQLite errors such as ABORT or extended
ABORT_ROLLBACK, rather than an empty-value success. `blob_close(blob)` always
destroys the token, even when reporting an engine error; all aliases become stale.
Connection close stays BUSY until all handles are destroyed.

**Incremental writes bypass SQL CHECK constraints and UPDATE triggers.** Use a
normal SQL UPDATE when those semantics are required. Existing column restrictions
and foreign-key policy still follow SQLite, but are not a substitute for CHECKs.
There is no implicit retry, reopen, transaction commit or rollback. On failure,
explicitly recover the transaction; earlier successful writes are not automatically
undone by this wrapper. See SQLite's [BLOB contract](https://sqlite.org/c3ref/blob_open.html)
and [close contract](https://sqlite.org/c3ref/blob_close.html).

## Bounded online backup

`backup(source,destination,max_pages) -> code` copies main to main synchronously.
Both databases must be distinct live handles on the current thread. Destination
must be writable, in autocommit, and have no live statements or BLOB handles;
violations return READONLY or INVALID_STATE. A source read transaction is allowed
and supplies its snapshot; an active source write transaction is INVALID_STATE.
Different connections to the same file are left to SQLite locking rules.

max_pages accepts 1..1048576. Calls request at most 64 pages per engine step and
charge every requested page, including if concurrent changes restart the backup.
DONE plus successful finish returns OK; budget exhaustion returns LIMIT. BUSY,
LOCKED and other errors are returned without wrapper retry. Finish always runs;
incomplete copies roll back destination changes using SQLite's backup transaction.
A failed finish is reported even after DONE. Back up to a separate file and verify
success before treating it as a recovery copy. Underlying I/O/hardware failures
remain SQLite/filesystem concerns. Source handles and the original file are not
modified by this operation.

A page budget bounds requested copying work, not elapsed time, allocator use,
disk space or total source size. Busy timeout and I/O can block within a step.
Page-size mismatches with an in-memory/WAL destination can fail (READONLY), as
specified by the [SQLite backup API](https://sqlite.org/c3ref/backup_finish.html).
No backup resource escapes the call; there is no hidden asynchronous operation.

## Statement diagnostics

`statement_status(stmt,metric,reset_counter) -> value,code` reads an allowlisted
SQLite statement metric in any live state, including Ready, Row, Done or Failed.
It does not execute, reset or finalize the statement. Invalid/default/stale/
foreign-thread/wrong-kind handles produce INVALID_HANDLE and zero output; an
unknown metric produces INVALID_INPUT and zero output. Check code separately
from the metric value.

| Metric | Meaning |
|---|---|
| STMT_FULLSCAN_STEPS | Table scan forward steps; useful when checking indexed queries |
| STMT_SORTS | Sort operations |
| STMT_AUTOINDEX_ROWS | Rows inserted into transient automatic indexes |
| STMT_VM_STEPS | VM operations, subject to SQLite's INT_MAX limit |
| STMT_REPREPARES | Automatic statement recompilations |
| STMT_RUNS | Executions started; increments on first step of each cycle |
| STMT_MEMORY_USED | Approximate bytes used by the prepared statement |

With reset_counter=true, the returned value is the previous counter and the
engine resets that counter to zero. This is independent of sqlite::reset(stmt).
STMT_MEMORY_USED is a gauge, so SQLite ignores reset_counter for that metric.
It is not process RSS or total SQLite allocator usage. The i64 output transports
SQLite's native int result; it does not create 64-bit counters. In particular,
STMT_VM_STEPS is undefined above 2147483647 operations; inspect/reset counters
periodically for long-running use. See the [engine counter contract](https://sqlite.org/c3ref/c_stmtstatus_counter.html).

The [runnable transaction example](../examples/transactions.goose) shows ownership
of a successful BEGIN, separate operation/recovery codes, nested savepoint cleanup,
and autocommit checks after INSERT OR ROLLBACK ends the entire transaction. A failed
BEGIN grants no right to roll back the caller's existing transaction. Inner RELEASE
is not an independent commit. Its fixed SQL/savepoint names are trusted code;
values use typed bindings. Both the runner and native example are tested.
