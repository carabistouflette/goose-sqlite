# Interface

All functions are in namespace `sqlite`. Interface is experimental. Connections
and statements are thread-affine, synchronous resources. Storage is owned by the
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

`Options { readonly=false, busy_ms=1000, work_budget=1000000 }`.
`open(path,options) -> Database,code`. Path is 1..4095 bytes with no NUL or `file:`
prefix. `:memory:` opens a private in-memory database. Other paths use ordinary
SQLite file semantics; caller controls path trust and filesystem permissions.
Readonly uses SQLITE_OPEN_READONLY; writable opens/creates. Failed open returns
an invalid zero-token Database and closes partially initialized SQLite state.
No journal/synchronous/durability setting is weakened by this module.

`close(db) -> code`: returns SQLITE_BUSY (5) while statements remain live. Busy
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

Per OS thread: 16 databases, 64 statements total. Allocation beyond a registry
limit returns LIMIT; finalizing/closing releases capacity. Tokens never repeat;
exhaustion fails closed. Thread exit finalizes live statements then closes
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
