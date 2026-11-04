# goose-sqlite

Small, synchronous SQLite connections and prepared statements for the
[Goose programming language](https://github.com/aardappel/goose). Apache-2.0.
Experimental interface; no tagged release yet. Initially tested on Linux x86-64.

Typed parameter binding, strict typed reads, explicit transactions, copied text
and blobs, incremental BLOB ranges, bounded backup, opt-in WAL, bounded input/work,
and checked resource handles. No ORM or pool.
SQLite is a required native dependency, not vendored in this repository.

## Quickstart

Install Git, CMake 3.27+, Make, Python 3, a C compiler, a C++20 compiler, pthreads,
SQLite 3.37+ development headers/library, and pkg-config. On Ubuntu 24.04:

```sh
sudo apt-get install build-essential cmake git python3 libsqlite3-dev pkg-config
# Clang is additionally required for sanitizer/fuzz checks.
git clone https://github.com/carabistouflette/goose-sqlite.git
cd goose-sqlite
make setup
make check test
.toolchain/goose/build/goose run examples/items.goose
```

The example prints `1: Goose`. `make setup` builds the exact compiler in
[GOOSE_REVISION](GOOSE_REVISION), with optional graphics/audio disabled. An
existing compiler at that revision can be selected with `make GOOSE=/path/to/goose`.
Linux's in-process runner also needs libc development headers.

## Usage

From a program next to a checkout named `goose-sqlite`:

```goose
import sqlite from "../goose-sqlite";
import std;

fn main() {
    let options = sqlite::Options { .. };
    let db, opened = sqlite::open(":memory:", options);
    assert(opened == sqlite::OK);
    let query, prepared = sqlite::prepare(db, "SELECT ?1");
    assert(prepared == sqlite::OK);
    assert(sqlite::bind_text(query, 1, "Hello, Goose!") == sqlite::OK);
    assert(sqlite::step(query) == sqlite::ROW);
    var text: u8[>..] = [];
    assert(sqlite::column_text(query, 0, text) == sqlite::OK);
    print(text);
    assert(sqlite::step(query) == sqlite::DONE);
    assert(sqlite::finalize(query) == sqlite::OK);
    assert(sqlite::close(db) == sqlite::OK);
}
```

Declare the package in your program's root file. A reviewed Git dependency can use
`import sqlite from "carabistouflette/goose-sqlite@e24de8ce7495c8146c6c9b408cf08686c981c182";`.
This pins the reviewed metadata/status, storage and statement-diagnostics interface. Imports and namespace are `sqlite`.
Applications must handle errors and clean up resources on their own error paths;
assertions above keep the example short. Native resource handles belong to their
OS thread. Copied handles alias one resource; closing/finalizing invalidates all
copies. Foreign-thread/stale/default handles return `INVALID_HANDLE`.

## Contract and scope

- Bindings copy values; returned bytes belong to the caller and survive cleanup.
- Parameter indices start at 1; column indices at 0. Reads require exact SQLite
  storage classes, including separate NULL, empty text and empty blob.
- `step` returns `ROW`, `DONE`, or an error. After DONE/error, call `reset` before
  reuse. Reset preserves bindings; `clear_bindings` is explicit.
- `execute` accepts one statement with no result columns. Queries and RETURNING
  are rejected before stepping; use `prepare`/`step` for them.
- Nonnegative results are SQLite codes, including extended error codes. Negative
  results are wrapper errors. Read [the full interface](docs/api.md) before use.
- Default busy timeout is 1000 ms; default approximate VM work budget is one
  million instructions per prepare/step. These are not total time/memory bounds.
- Defensive connection policies deny PRAGMA, ATTACH/DETACH, extension loading,
  and virtual table creation/deletion. Virtual tables and VACUUM are unsupported.
  Filenames cannot be `file:` URIs. Ordinary file access is not sandboxed.

[Platforms and requirements](docs/platforms.md) · [Security](SECURITY.md) ·
[Contributing](CONTRIBUTING.md) ·
[Benchmarks](bench/README.md) · [Validation](docs/validation.md) ·
[Third-party notices](THIRD_PARTY_NOTICES.md)

Named parameters and metadata are available through `parameter_count`,
`parameter_index` and copied `column_name`. `changes`, `last_insert_rowid` and
`autocommit` expose checked connection status. See [alternative features](docs/alternatives.md)
and the [matched-engine benchmark methodology](bench/alternatives/README.md) for
scope, remaining gaps and performance comparison rules.

`Options.wal` provides verified WAL initialization on recognized engines with
SQLite's WAL-reset fix, preserving at least FULL synchronization. `blob_open`,
`blob_size`, `blob_read`, `blob_write`, `blob_close` and `backup` add checked storage
operations. Writable BLOBs require explicit transactions and bypass SQL CHECKs
and UPDATE triggers; read [the contract and limits](docs/api.md) before using them.
WAL requires a suitable local filesystem and patched engines for all participants.

The [incremental-read results](bench/results/storage-2026-11-04/README.md) retain
two complete nine-round series, including the disclosed CPU overlap. Partial reads
benefit from copying only the needed range; full-value reads favor column_blob.
Both raw SQLite C and Goose can use this API. No universal ranking is claimed.

Storage recovery checks inject I/O/full/sync errors and process crashes, including
death after acknowledged commits. See [methodology and retained results](tests/RECOVERY.md)
for the completed compiler/engine matrix and the process-crash/power-loss distinction.

`statement_status` exposes checked scan/sort/VM/run and approximate statement-memory
metrics. The [transaction/savepoint example](examples/transactions.goose) preserves
original and recovery errors explicitly. [Realistic workload results](bench/results/workloads-2026-11-04/README.md)
retain ten fixtures across five callers, whole-process peak RSS and matched registry
measurements, including mixed/slower cases and the native-executable timing scope.
