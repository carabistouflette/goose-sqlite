# Design and initial contract

Small synchronous SQLite module, using the system SQLite library (3.37+),
validated on Linux x86-64 and ARM64. No ORM, pool, SQL builder, extension loader,
or implicit transactions. Native SQLite is fundamental, so unlike goose-json
there is no portable Goose fallback.

Connections and statements contain copyable opaque integer tokens, never native
pointers. A per-thread registry validates every use; tokens are unique across
threads and lifetimes and never wrap. Maximum 16 connections and 64 statements
per OS thread. Thread-exit cleanup finalizes statements before closing databases.
Explicit close returns SQLITE_BUSY with live statements. Explicit finalize
invalidates all copies even when it reports an execution error. Tokens are
accidental-misuse protection, not capabilities against hostile native code.

Statements move Ready -> Row -> Done/Failed. Bind/clear require Ready; step
accepts Ready/Row; getters require Row. Reset restores Ready and retains bound
values, even when returning the previous execution error. Done/Failed require
reset before another step. Callers must inspect reset/finalize errors and finish
RETURNING statements before assuming a write committed.

Bindings copy input. Text and blobs preserve embedded NUL bytes; empty values
are distinct from NULL. Text is SQLite UTF-8 byte text, without an independent
UTF-8 validator. Typed getters require exact storage classes. Float binding
rejects nonfinite values. Byte getters copy to caller-owned storage, clearing it
on failure; data survives reset/finalize/close. Indices are one-based parameters,
zero-based columns. SQLite extended result codes remain visible. Negative
wrapper codes represent invalid input/handle/state/type/limits.

One nonempty statement per prepare; trailing whitespace and comments accepted,
second statements and embedded SQL NUL rejected. SQL is application code; bind
untrusted values. Filenames reject `file:` URIs; ordinary SQLite file access is
not a filesystem sandbox. Defensive mode enabled, trusted schema disabled,
foreign keys enabled, extension loading disabled. An authorizer rejects ATTACH,
DETACH, virtual table creation/deletion and all PRAGMA statements, preserving
initial connection policies. Virtual tables and VACUUM are unsupported.

Limits: SQL 64 KiB, values/encoded rows 1 MiB, columns 128, parameters 128,
expression depth 64, compound SELECT terms 32, VDBE opcodes 250000, trigger
depth 16, attached databases zero, SQLite worker threads zero. Busy timeout
0..30000 ms. Per-prepare/per-step progress budget 1000..100000000 instructions,
default 1000000, checked approximately every 1000 instructions. These are work
limits, not fixed memory/disk/time limits or a SQL sandbox. SQLite version affects
prepare progress coverage. A result stream can have unlimited total rows.

SQLite must be built with thread safety and must not be globally configured in
single-thread mode by the application. This module does not change process-global
SQLite configuration. Independent connections can run on independent threads.

Validation follows goose-json: pinned Goose compiler, standalone quickstart,
public Goose behavior tests under runner/native build, production C adapter
under GCC/Clang ASan/UBSan and libFuzzer, focused Conventional Commits, repeated
independent security/correctness/performance review, raw benchmark samples with
source/toolchain/environment provenance. Optimize only measured costs.

Design references: https://sqlite.org/c3ref/stmt.html,
https://sqlite.org/c3ref/step.html, https://sqlite.org/c3ref/reset.html,
https://sqlite.org/c3ref/c_dbconfig_defensive.html,
https://sqlite.org/limits.html, https://sqlite.org/c3ref/progress_handler.html.
