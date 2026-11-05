# Security

Report suspected vulnerabilities through
[GitHub Security Advisories](https://github.com/carabistouflette/goose-sqlite/security/advisories/new).
Include the affected commit, Goose and SQLite versions, platform, and a small
reproducer. Avoid publishing exploit details before a fix is available.

## Trust boundary

SQL is application code. Use typed bindings for untrusted values; the library
does not provide SQL escaping or interpolation. Database files are untrusted
inputs to the system SQLite parser. Install security updates for the SQLite
package provided by your operating system.

The connection enables defensive mode and foreign keys, disables trusted
schemas and extension loading, and denies PRAGMA, ATTACH/DETACH and virtual-table
creation/deletion. This is a restricted interface, not a sandbox for hostile SQL.
The library does not confine filesystem paths, reject symlinks, encrypt data,
isolate processes, or protect against hostile native code in the same process.
Ordinary file access follows SQLite and operating-system rules.

The wrapper copies input values before binding and copies returned bytes into
Goose-owned arrays. Opaque tokens are checked for handle type, lifetime and
owning thread before use. These checks prevent accidental stale-handle use; they
are not a security boundary against native code in the process.

## Limits

SQL, value, VM and handle limits are described in the
[API contract](docs/api.md). They limit individual inputs and operations, not
total elapsed time, memory, disk use or I/O. The VM budget does not cover native
functions or filesystem work, and callers can read an unlimited number of rows.
Handle caps are per OS thread, not per process.

SQLite must be built with thread safety enabled and must not be placed in
single-thread mode through process-global configuration. Call initialize on one
startup thread after any native SQLite configuration and before worker threads
start. Check its result.

## Storage operations

WAL is accepted only on recognized SQLite versions with the WAL-reset fix. Every
process accessing a WAL database must use a fixed engine version. WAL also needs
a suitable local filesystem and accessible sidecar files; see the
[version rules](docs/api.md).

Incremental BLOB writes require an explicit transaction and bypass SQL CHECK
constraints and UPDATE triggers. Use SQL UPDATE when those checks must run.
Online backup limits requested pages, not elapsed time, memory or disk space.
Check operation results and verify backups before relying on them.

## Validation limits

The native adapter is tested with GCC and Clang sanitizers, fuzzing, and fault
injection. The system SQLite library is not instrumented by ordinary system-engine
tests. Separate CI builds instrument a pinned engine for positive-WAL checks.

The maintained TSan test initializes SQLite on one thread before starting workers.
Separate cold-start TSan tests reproduce reports inside unmodified SQLite 3.54.1
under static and shared linkage. The cause is unresolved; this is neither a clean
concurrent cold-start result nor proof that the report is a C-level race. No
production workaround was added. See the [TSan scope](tests/CONCURRENCY.md) and
[cold-start evidence](tests/results/cold-start-2026-11-05/README.md).

Storage fault tests preserve the OS cache. They test process crashes and injected
I/O errors, not power loss, torn writes or hardware failures. See
[recovery test scope](tests/RECOVERY.md).
