# Alternatives

This feature comparison is a source review, not a claim that one wrapper is best
for every application. It compares goose-sqlite at runtime baseline
70ebfc263a1d1d8714899d5ec43510076668f5b5 with selected fixed upstream snapshots.
Alternative packages were inspected, not run, except where a benchmark record says
otherwise. See [benchmark currentness](../bench/CURRENTNESS.md) before using any
timing result.

## Packages reviewed

| Package | Snapshot inspected | Engine and license |
|---|---|---|
| goose-sqlite | 70ebfc263a1d1d8714899d5ec43510076668f5b5 | System SQLite; Apache-2.0 |
| kaitk/goose-sqlite | 2c315b48fe0f479e4eb172b99403d35ae7d1cdcf | Vendored SQLite; Apache-2.0 or MIT |
| shetautnetjer/goose-sqlite | e29f01b04f26409623c61ba72f1df948af63355a | Vendored SQLite; MIT |
| CPython sqlite3 | CPython 3.15.2, commit 5e58eaad7c58df58dfa8ea549c87996e01dd1077 | System SQLite; PSF license |
| rusqlite | 0.41.1, commit 18ee76dbb976d5ef7e37ad5a8fffae678ca21a78 | System SQLite by default; optional bundled engine; MIT |
| SQLiteCpp | 3.4.0, commit df0a28ca9733f687ab7ce77f070c0df84368a45e | System or bundled engine; MIT |
| SQLite C API | SQLite 3.54.1 | Engine is public domain |

Sources: [kaitk README](https://github.com/kaitk/goose-sqlite/blob/2c315b48fe0f479e4eb172b99403d35ae7d1cdcf/README.md),
[kaitk API](https://github.com/kaitk/goose-sqlite/blob/2c315b48fe0f479e4eb172b99403d35ae7d1cdcf/sqlite.goose),
[shetautnetjer README](https://github.com/shetautnetjer/goose-sqlite/blob/e29f01b04f26409623c61ba72f1df948af63355a/README.md),
[shetautnetjer adapter](https://github.com/shetautnetjer/goose-sqlite/blob/e29f01b04f26409623c61ba72f1df948af63355a/src/gsq.c),
[CPython sqlite3](https://docs.python.org/3.15/library/sqlite3.html),
[rusqlite features](https://github.com/rusqlite/rusqlite/blob/v0.41.1/Cargo.toml),
[SQLiteCpp README](https://github.com/SRombauts/SQLiteCpp/blob/3.4.0/README.md),
and [SQLite license](https://sqlite.org/copyright.html).

The two Goose packages are independent projects with different APIs and engine
deployment choices. Their READMEs report consumers and test coverage; those
reports were not independently verified here. Search results are not a complete
catalog of Goose libraries.

## Feature comparison

| Area | goose-sqlite | Other wrappers |
|---|---|---|
| Statements and values | Prepared statements; copied bindings; typed reads require the exact SQLite storage class. | All expose prepared or cached execution. Python returns Python values, rusqlite offers typed conversions, SQLiteCpp offers C++ conversions, and raw C exposes SQLite's conversions and borrowed pointers. |
| Metadata and status | Parameter lookup/count, copied column names, changes, rowid, autocommit and main-schema transaction state. | Most expose some or all of these. Names, status semantics, value ownership and feature flags differ by package. |
| Transactions | Explicit SQL transactions and savepoints; callers inspect every result and recover errors. | Python adds connection helpers/context managers; rusqlite and SQLiteCpp provide transaction guards. Raw C leaves policy to the caller. |
| Resource lifetime | Opaque, thread-affine handles with stale-handle checks, explicit cleanup and thread-exit cleanup. | Rust and C++ use language lifetime/RAII patterns. Python uses object lifetime and explicit close. Raw C uses pointers and explicit cleanup. The other Goose packages use their own handle schemes. |
| Backup and incremental BLOBs | Bounded online backup and checked incremental BLOB handles. BLOB writes require a transaction and bypass SQL CHECK constraints and UPDATE triggers. | Python and rusqlite expose these through their APIs or optional modules. SQLiteCpp exposes backup; the inspected public API has no dedicated incremental BLOB type. Raw C exposes both APIs. |
| WAL and connection policy | Optional WAL with a conservative engine-version check; arbitrary PRAGMA, ATTACH/DETACH and virtual-table creation/deletion are denied. | Other wrappers generally expose SQLite's configuration more directly. Available callbacks, limits and extension support depend on package and build features. |
| User-defined functions and extensions | Not exposed; extension loading is disabled. | Python, rusqlite, SQLiteCpp and raw C expose some callback or extension APIs. |
| Engine and platforms | Uses system SQLite; tested on Linux x86-64 and ARM64. | Deployment varies. rusqlite and SQLiteCpp can use a bundled engine; the two other Goose packages inspect here vendor SQLite. Their platform claims belong to those projects. |

The [API contract](api.md) describes exact limits and errors. The
[security page](../SECURITY.md) explains what the connection policy does and
does not protect. SQLite features such as JSON functions, indexes and RETURNING
depend on the installed engine version and build.

## Differences to keep in mind

- Goose has no destructors, so its explicit cleanup and thread-exit cleanup are
  not equivalent to Rust or C++ RAII.
- goose-sqlite rejects stale or cross-thread handles. One inspected Goose package
  uses generation handles; the other converts native pointers to integer handles
  and expects callers to follow its cleanup contract. These are different APIs,
  not a measured safety ranking.
- goose-sqlite deliberately omits UDFs, extension loading, virtual tables,
  arbitrary PRAGMA and a connection pool.
- Using the system engine makes engine updates an operating-system responsibility.
  Bundling an engine can simplify deployment but changes update and package-size
  tradeoffs.

## Performance evidence

The retained cross-wrapper measurement uses exact source revisions, a shared
SQLite library, and copied result values. Its source predates the current
BLOB/text materialization helper, so its timing table is historical, not a
current ranking. Raw samples and the source details remain in the
[2026-11-04 result record](../bench/results/alternatives-2026-11-04/README.md).
No current speed advantage is claimed from that table.
