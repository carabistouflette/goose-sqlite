# goose-sqlite

A synchronous SQLite binding for the [Goose language](https://github.com/aardappel/goose).
It uses the system SQLite library. The source is Apache-2.0.

**Status:** experimental; no release tag is published. The runtime source reviewed
for this documentation is public commit
[`70ebfc2`](https://github.com/carabistouflette/goose-sqlite/commit/70ebfc263a1d1d8714899d5ec43510076668f5b5).
That snapshot passed [its three CI jobs](https://github.com/carabistouflette/goose-sqlite/actions/runs/42084238303).
The docs update does not change the runtime.

Tested platforms are Linux x86-64 and ARM64. Other platforms are unverified.
SQLite 3.37 or newer is required for the base API. Optional WAL requires a
recognized SQLite version with the WAL-reset fix; see [platform requirements](docs/platforms.md).

## Quick start

On Ubuntu 24.04, install the compiler and SQLite development files, then run the
included example:

```sh
sudo apt-get install build-essential cmake git python3 libsqlite3-dev pkg-config
git clone https://github.com/carabistouflette/goose-sqlite.git
cd goose-sqlite
make setup
.toolchain/goose/build/goose run examples/items.goose
```

The example prints `1: Goose`. `make setup` builds the exact compiler commit in
[GOOSE_REVISION](GOOSE_REVISION). Goose requires C++20; this package's native
adapter requires a C compiler. Linux runner builds also need libc development
headers. To run the correctness suite, use `make check test`.

In an application, import a full source commit rather than a moving branch. For
example, this imports the reviewed runtime snapshot above:

```goose
import sqlite from "carabistouflette/goose-sqlite@70ebfc263a1d1d8714899d5ec43510076668f5b5";
```

The namespace is `sqlite`. The runnable programs in [`examples/`](examples/)
show prepared statements and transaction recovery.

## What the API provides

- Prepared statements, typed bindings and exact-type reads. Input and output
  text/blob bytes are copied; empty text, empty BLOB and NULL remain distinct.
- Explicit transactions and savepoints, connection status, statement metadata
  and diagnostics, incremental BLOB access, page-bounded online backup, and
  opt-in WAL/checkpoints.
- Thread-affine opaque handles, stale-handle checks and thread-exit cleanup.
  A handle copy aliases the same resource; closing or finalizing invalidates all
  copies. Check every returned result and clean up on error paths.

Read [the API contract](docs/api.md) before relying on lifecycle, error or storage
details. In particular, `step` returns `ROW`, `DONE` or an error; reset before
reusing after `DONE` or an error. `execute` accepts one statement with no result
columns. It does not start a transaction for you.

## Limits and security

The default busy timeout is 1 second and the default approximate VM budget is
1,000,000 instructions per prepare and step. Neither bounds total elapsed time,
memory, disk use, I/O, or the number of rows a caller reads. SQL/value limits and
per-thread handle limits are documented in the [API](docs/api.md).

The connection denies PRAGMA, ATTACH/DETACH, extension loading and virtual-table
creation/deletion. Virtual tables and VACUUM are unsupported. This is not a SQL
sandbox: SQL is application code, database parsing relies on system SQLite, and
ordinary filenames use normal operating-system path rules. Writable incremental BLOB operations bypass
SQL CHECK constraints and UPDATE triggers. See [security limits](SECURITY.md).

## Performance and validation

There is no general performance ranking. Each benchmark is tied to its recorded
source, tools, engine and workload. [Benchmark currentness](bench/CURRENTNESS.md)
marks which results still match the runtime and which are historical snapshots.
Raw samples and protocols are linked from the [benchmark guide](bench/README.md).

[Validation summary](docs/validation.md) · [Platform support](docs/platforms.md) ·
[Design](docs/design.md) · [Alternatives](docs/alternatives.md) ·
[Contributing](CONTRIBUTING.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)
