# Security

Report suspected vulnerabilities privately through
[GitHub security advisories](https://github.com/carabistouflette/goose-sqlite/security/advisories/new).
Include the affected commit, compiler/SQLite versions, platform and a minimal
reproducer. Avoid public exploit details before a fix is available.

## Trust and ownership

SQL is application code. Use typed bindings for untrusted data; no SQL escaping
or string interpolation helper is provided. Filenames and file permissions are
application policy. This module does not provide no-follow traversal, path
confinement, encryption, process isolation or protection against hostile native
code. Do not treat its authorizer as a general untrusted-SQL sandbox.

The system SQLite library is a runtime dependency: install security updates from
your operating system. The supported minimum version is an interface requirement,
not a security endorsement of every old SQLite release. Malicious database files
exercise SQLite's native parser and engine. Defensive mode and limits reduce
some risks but do not replace an updated engine or isolation where needed.

Goose owns input/output arrays. Bindings are copied before return; results are
copied before SQLite storage can change. Default, foreign-thread and stale handle
copies are validated before touching native resources. Tokens prevent accidental
use-after-free; native code in the same process is trusted. Scalar ABI outputs
use memcpy because Goose references may be byte-aligned.

## Policies and limits

Defensive mode, foreign keys, untrusted schemas and disabled extension loading
are checked at connection creation. The opt-in WAL mode uses fixed private
initialization SQL before the public authorizer and verifies its result, preserving
at least FULL synchronization. All caller SQL PRAGMAs, ATTACH/DETACH and virtual
table creation/deletion are denied. URI filenames are rejected independently of
SQLite's process-global URI configuration. Ordinary filenames follow SQLite's
normal filesystem semantics, including symlinks.

Input/VM/registry bounds are documented in [the interface](docs/api.md). They are
not a fixed allocator, execution-time or disk-space budget. The progress callback
covers VM work approximately; native functions and I/O can exceed it in time.
A caller can iterate indefinitely over bounded individual rows. Thread limits
are per thread, not per process. System SQLite must remain in a thread-safe mode.

## Validation scope

Public Goose tests run under the in-process runner and a native executable.
Native production adapter tests run with GCC/Clang ASan/UBSan, and its fuzzer
exercises malformed SQL, arbitrary text/blob bytes, capacity checks, stale
handles and a model of statement operation sequences. A separate native test
process injects SQLite allocation failures and checks recovery/cleanup; allocator
hooks are test-only and installed before SQLite initialization. The installed system SQLite itself is not sanitizer-instrumented
by the system-engine checks. The optional pinned-engine validation separately
builds both SQLite and the adapter with ASan/UBSan and exercises positive WAL
behavior with DEFAULT_WAL_SYNCHRONOUS=1. Native CI covers Linux x86-64 and
ARM64. Separate x86-64 TSan validation instruments both engine and adapter after
explicit serial engine initialization; first registry/key use remains concurrent. Cold
engine initialization under TSan produced unresolved upstream diagnostics, retained
with the results. Ordinary ASan/UBSan runs retain concurrent cold initialization.
See [concurrency methodology](tests/CONCURRENCY.md) for these exact limits.
See [the validation record](docs/validation.md) for exact completed checks.

## Storage features

WAL is accepted only on recognized SQLite versions containing the WAL-reset
corruption fix (see [API version rules](docs/api.md)). Unknown backports fail
closed; all other processes using that file must also use a patched engine.
Opening is not atomic with external changes of journal mode.
Checkpoint accepts only four explicit modes on a writable, idle main connection.
It preserves the SQL authorizer and synchronization policy. Its VM budget does
not bound I/O or elapsed time, and BUSY can report partial progress. Frame counts
are engine-sized; unavailable/error outputs are -1. See the API contract.

Incremental BLOB reads copy owned ranges with checked arithmetic. Writable BLOBs
require an explicit transaction, but **bypass CHECK constraints and UPDATE
triggers**, as SQLite specifies; use SQL UPDATE when those checks are required.
Always close handles, inspect errors, and explicitly recover failed transactions.
Backup bounds requested pages and always finishes its internal handle; it does
not impose a disk/heap/time limit. Verify success before relying on a backup.

A separate test-only VFS injects read/write/full/sync/truncate/delete/SHM failures and process death
across transaction, incremental BLOB, backup and checkpoint operations. Fresh connections
verify integrity and complete old/new generations; checkpoints must preserve the
already committed generation, and acknowledged commits must
survive process termination. These finite tests preserve the OS cache; they do
not simulate torn writes or power loss. See [recovery methodology](tests/RECOVERY.md)
and its retained records for exact scope and completed checks.
