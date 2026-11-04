# goose-sqlite

Small, synchronous SQLite connections and prepared statements for the
[Goose programming language](https://github.com/aardappel/goose). Apache-2.0.
Experimental interface; no tagged release yet. Initially tested on Linux x86-64.

Typed parameter binding, strict typed reads, explicit transactions, copied text
and blobs, bounded input/work, and checked resource handles. No ORM or pool.
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
`import sqlite from "carabistouflette/goose-sqlite@c03efc275ba22100233d16ee51d111eabe60dff0";`.
This pins the reviewed buffer-reuse implementation and regression coverage. Imports and namespace are `sqlite`.
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
