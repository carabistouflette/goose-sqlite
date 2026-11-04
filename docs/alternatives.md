# SQLite alternatives and practical parity

Research snapshot: 2026-11-04. This is a design and measurement proposal, not a
performance result or a claim of full API parity. Scope is synchronous SQLite
bindings, not ORMs. No alternative was built or benchmarked during this research.

## Local baseline and reproducible identities

The inspected standalone repository was on `feat/alternative-parity`, clean at
`272193c9b2a7db6aa81f407f623a4eff4c0e66f0`. Its Goose compiler pin is
`eadca409f68210893f366e60d0c2f0dc29a339be`. Local evidence:
[README](../README.md), [API contract](api.md), [contribution rules](../CONTRIBUTING.md),
[public API](../sqlite.goose), [native adapter](../native/sqlite.c), and
[existing benchmark methodology](../bench/README.md). Current API entries in the
matrix below refer to these files at this revision, not future implementation.
The package has no tagged release and uses Apache-2.0 ([license](../LICENSE)).

Exact upstream comparison snapshots (release tags resolved through the projects'
GitHub commit API, not inferred from a moving default branch):

| Component | Version and revision examined | License and first-party evidence |
|---|---|---|
| CPython stdlib `sqlite3` | CPython **3.15.2**, tag `v3.15.2`, commit `5e58eaad7c58df58dfa8ea549c87996e01dd1077` | [Release](https://www.python.org/downloads/release/python-3152/), [revision](https://github.com/python/cpython/commit/5e58eaad7c58df58dfa8ea549c87996e01dd1077), [PSF license and historical notices](https://github.com/python/cpython/blob/v3.15.2/LICENSE); `_sqlite` source also carries Gerhard Häring's permissive notice ([module](https://github.com/python/cpython/blob/v3.15.2/Modules/_sqlite/module.c)) |
| Rust `rusqlite` | **0.41.1**, tag `v0.41.1`, commit `18ee76dbb976d5ef7e37ad5a8fffae678ca21a78` | [Release](https://github.com/rusqlite/rusqlite/releases/tag/v0.41.1), [MIT manifest and optional features](https://github.com/rusqlite/rusqlite/blob/v0.41.1/Cargo.toml) |
| C++ `SQLiteCpp` | **3.4.0**, commit `df0a28ca9733f687ab7ce77f070c0df84368a45e` | [Release](https://github.com/SRombauts/SQLiteCpp/releases/tag/3.4.0), [MIT](https://github.com/SRombauts/SQLiteCpp/blob/3.4.0/LICENSE.txt); this release line supports C++11, unlike planned 4.x |
| Raw SQLite C | **3.54.1**, upstream source ID `2026-10-16 14:45:20 555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6ca76` | [Release and amalgamation SHA3](https://www.sqlite.org/releaselog/3_54_1.html), [public-domain dedication](https://www.sqlite.org/copyright.html) |

The installed host is different from the CPython reference release: Python
**3.14.9**, GCC **16.2.1 20260810**, rustc **1.101.0-nightly
(822182db4 2026-10-13)** and cargo **1.101.0-nightly (29c5daa1a
2026-10-07)**. `pkg-config --modversion sqlite3` and Python's
`sqlite3.sqlite_version` both report **3.54.1**, but Python's actual
`sqlite_source_id()` is
`2026-10-16 14:45:20 555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6alt1`.
That `alt1` suffix differs from upstream: never equate matching version numbers
with identical engine builds. These are inspection observations, not stored
benchmark provenance or a requirement to use a nightly compiler.

## Other Goose packages exist

Here Goose means [aardappel/goose](https://github.com/aardappel/goose), not Go's
migration tool or another language sharing the name. GitHub repository searches
for `goose sqlite` and `goose-sqlite in:name`, followed by first-party source
inspection, found two relevant alternatives. Search is not proof of completeness;
GitHub's `language:Goose` filter did not reliably restrict results. The compiler's
[current blessed package list](https://github.com/aardappel/goose/blob/master/src/blessed.txt)
is also not an exhaustive ecosystem registry.

* **[kaitk/goose-sqlite](https://github.com/kaitk/goose-sqlite/tree/2c315b48fe0f479e4eb172b99403d35ae7d1cdcf)**:
  inspected default-branch commit `2c315b48fe0f479e4eb172b99403d35ae7d1cdcf`;
  advertised release `v0.0.3` resolves to
  `3f0deef9d4fb789577da73c304a53922aa162ec9` (different snapshot).
  [README](https://github.com/kaitk/goose-sqlite/blob/2c315b48fe0f479e4eb172b99403d35ae7d1cdcf/README.md)
  identifies Plod as a consumer, tests, vendored SQLite 3.54.1, and
  **Apache-2.0 OR MIT** licensing, with SQLite public domain. It exposes named
  parameter lookup/count, column names, changes, rowid, transaction status,
  read-only flags and arbitrary PRAGMA execution including WAL. It provides
  `run` error blocks and nested transaction/savepoint blocks. Its documented
  caveats include ordinary `return` skipping transaction completion, and cleanup
  APIs discarding reset/finalize errors. The
  [API](https://github.com/kaitk/goose-sqlite/blob/2c315b48fe0f479e4eb172b99403d35ae7d1cdcf/sqlite.goose)
  and [shim](https://github.com/kaitk/goose-sqlite/blob/2c315b48fe0f479e4eb172b99403d35ae7d1cdcf/shim/sqlite.c)
  show copied binding/output, generation-based handles, mutex use and SQLite's
  coercing numeric getters. Those are different contracts from this package's
  strict reads, thread-affine tokens and checked cleanup errors. Platform/test
  claims are upstream reports; this research did not validate them independently.
* **[shetautnetjer/goose-sqlite](https://github.com/shetautnetjer/goose-sqlite/tree/e29f01b04f26409623c61ba72f1df948af63355a)**:
  inspected commit `e29f01b04f26409623c61ba72f1df948af63355a`; advertised
  `v0.1.1` resolves to `3971e87e7f6ca01ff55fd1e52b66ae9d9dbffee5`.
  Its [README](https://github.com/shetautnetjer/goose-sqlite/blob/e29f01b04f26409623c61ba72f1df948af63355a/README.md)
  names Swan as its consumer and reports 43 standalone checks. MIT wrapper,
  vendored public-domain SQLite 3.54.1. Smaller integer/text API, copied text,
  rowid, SQL transaction support and abort-on-error conveniences. The
  [shim](https://github.com/shetautnetjer/goose-sqlite/blob/e29f01b04f26409623c61ba72f1df948af63355a/src/gsq.c)
  casts native pointers into integer handles; caller cleanup discipline replaces
  stale-token validation. Its documented `SQLITE_THREADSAFE=0` build requires
  caller serialization, and reset also clears bindings. These differences make
  an unqualified safety/performance ranking inappropriate.

Both warrant evaluation as real packages, without treating early releases or
claimed downstream use as evidence of maturity. Neither was run here.
[SteelSeries/goose-sqlite](https://github.com/SteelSeries/goose-sqlite) and
[pressly/goose](https://github.com/pressly/goose) are Go migration tools;
[alloyapple/GooseSqlite](https://github.com/alloyapple/GooseSqlite) is Swift.
They are not competing aardappel-Goose bindings.

## Feature matrix

“SQL” means engine syntax reachable through the wrapper, not a dedicated wrapper
API. “C escape” means accessing an exposed native handle; that is not equivalent
to a checked high-level wrapper method. Optional features and engine compile
options must be recorded. Citations for each alternative's cells follow the table.

| Capability | Current goose-sqlite | Python stdlib sqlite3 | Rust rusqlite | C++ SQLiteCpp | Raw SQLite C |
|---|---|---|---|---|---|
| Reusable prepared work | Explicit prepare/reset, persistent hint | SQL statement cache; cursor execute, no public prepared handle | Statement and cached preparation | Statement/reset | prepare/step/reset/finalize |
| Typed values, NULL, whole text/blob | Strict storage types, caller-owned copies | Python values; owned str/bytes | Typed conversions; owned or borrowed results | Typed/coercing getters; borrowed pointers or owned strings | Storage-type inspection; coercing getters, borrowed pointers |
| Named binding | SQL names accepted, numeric binding only | Named dictionary binding | Named binding and index lookup | Named binding and `getIndex` | Named index API |
| Parameter count | Not exposed | No public statement-count API | `parameter_count` | `getBindParameterCount` | Largest parameter index |
| Result column names | Count/type only | Cursor.description; optional Row lookup | Names and name lookup | Names and name lookup | `sqlite3_column_name` |
| Changed rows / last insert rowid | SQL `changes()` / `last_insert_rowid()`; no direct API | rowcount / lastrowid; total_changes | changes / last_insert_rowid | getChanges / getLastInsertRowid | changes64 / last_insert_rowid |
| Engine autocommit state | Not exposed | `in_transaction` (inverse); distinct from Python `autocommit` policy | is_autocommit | C escape | get_autocommit |
| Explicit transaction / savepoint | Both via single-statement SQL | SQL plus commit/rollback and context manager | SQL plus transaction/savepoint guards | SQL plus Transaction/Savepoint guards | SQL |
| Read-only open | Bounded option | URI mode=ro | OpenFlags | OPEN_READONLY (constructor default) | SQLITE_OPEN_READONLY |
| WAL configuration | Can use existing WAL DB; PRAGMA configuration denied | SQL PRAGMA | PRAGMA helpers/SQL | SQL PRAGMA | SQL PRAGMA |
| Busy/work bounds | Bounded timeout and approximate per-call VM budget; fixed limits | Timeout, progress/authorizer callbacks, runtime limits | Timeout/handlers; hooks/limits features | Busy timeout; further controls via C escape | Timeout/progress/limits/authorizer primitives |
| Backup | Absent | Connection.backup | Optional backup module | Database.backup | Online backup API |
| Incremental BLOB handles | Absent (whole blobs supported) | blobopen | Optional blob module | No dedicated class in inspected public API; C escape | blob_open/read/write/close |
| UDF / extension loading | Absent; extension loading disabled | Functions/aggregates/windows; extension support depends on build | Optional functions; unsafe extension API | createFunction / loadExtension | Callback and extension APIs |
| Lifetime cleanup | Explicit plus thread-exit cleanup; alias-invalidating tokens | Explicit close/context tools; transaction context does not close DB | Drop/lifetime guards | RAII destruction | Explicit; caller pointer discipline |

Python evidence: [3.15 sqlite3 reference](https://docs.python.org/3.15/library/sqlite3.html),
[connection implementation](https://github.com/python/cpython/blob/v3.15.2/Modules/_sqlite/connection.c),
[cursor implementation](https://github.com/python/cpython/blob/v3.15.2/Modules/_sqlite/cursor.c).
Rust evidence: pinned [connection](https://github.com/rusqlite/rusqlite/blob/v0.41.1/src/lib.rs),
[statement](https://github.com/rusqlite/rusqlite/blob/v0.41.1/src/statement.rs),
[column](https://github.com/rusqlite/rusqlite/blob/v0.41.1/src/column.rs),
[transaction](https://github.com/rusqlite/rusqlite/blob/v0.41.1/src/transaction.rs),
and [feature manifest](https://github.com/rusqlite/rusqlite/blob/v0.41.1/Cargo.toml).
C++ evidence: pinned [Database](https://github.com/SRombauts/SQLiteCpp/blob/3.4.0/include/SQLiteCpp/Database.h),
[Statement](https://github.com/SRombauts/SQLiteCpp/blob/3.4.0/include/SQLiteCpp/Statement.h),
[Column](https://github.com/SRombauts/SQLiteCpp/blob/3.4.0/include/SQLiteCpp/Column.h),
[Transaction](https://github.com/SRombauts/SQLiteCpp/blob/3.4.0/include/SQLiteCpp/Transaction.h),
[Savepoint](https://github.com/SRombauts/SQLiteCpp/blob/3.4.0/include/SQLiteCpp/Savepoint.h).
C evidence: [API inventory](https://www.sqlite.org/c3ref/funclist.html),
[binding ownership](https://www.sqlite.org/c3ref/bind_blob.html),
[column value lifetime/conversion](https://www.sqlite.org/c3ref/column_blob.html),
[backup](https://www.sqlite.org/c3ref/backup_finish.html),
[incremental blobs](https://www.sqlite.org/c3ref/blob_open.html).

Indexes, joins, transactions, savepoints, RETURNING, JSON functions and WAL are
SQLite engine features, conditional on engine version/build and policy. A wrapper
cannot claim a better query engine merely by exposing them. Named-parameter
lookup, copied metadata, transaction guards and row mapping are wrapper
conveniences. This package deliberately restricts PRAGMA, ATTACH/DETACH, virtual
tables, extension loading and URI filenames, and forbids automatic reexecution
and implicit coercion. Retain these distinctions when describing parity.

## Recommended first expansion

Recommendation: one coherent **checked metadata and connection-status** slice.
Keep the existing two resource types, explicit cleanup and result-code convention.
Do not copy another wrapper's full API or add pointers, callbacks, registries,
implicit retries or a general configuration escape hatch.

1. `parameter_count(stmt) -> count_or_error` and
   `parameter_index(stmt,name) -> index_or_error`. Preserve SQLite's lookup
   convention: zero means absent, negative means wrapper failure; require the
   exact parameter spelling including `:`, `@`, `$` or numbered `?` prefix,
   bounded nonempty bytes and no NUL. Reuse existing numeric binders after lookup.
   Document that count is the **largest parameter index**, not the number of
   occurrences or necessarily distinct placeholders: `SELECT ?5, :x, :x` has
   largest index six, with holes. No implicit “every slot must be bound” rule.
   Sources: [count](https://www.sqlite.org/c3ref/bind_parameter_count.html),
   [lookup](https://www.sqlite.org/c3ref/bind_parameter_index.html).
2. `column_name(stmt,index,out) -> code`, copying bytes into caller storage with
   an explicit bound and output cleared on failure. Permit valid statement
   states as for column_count, independently of Row-only value getters. Copy on
   each request: automatic reprepare invalidates native metadata pointers.
   Require SQL aliases when callers need stable names; duplicate names remain
   valid. Avoid a second name-to-index API until its ambiguity semantics matter.
   Source: [column names](https://www.sqlite.org/c3ref/column_name.html).
3. `changes(db) -> value,code`, `last_insert_rowid(db) -> value,code` and
   `autocommit(db) -> value,code`. Rowids can be negative, so do not overload the
   value with negative error codes. Use `sqlite3_changes64`; document that it is
   last completed direct DML on the connection, excluding auxiliary trigger/FK
   effects and not a count of committed rows. Rowid excludes WITHOUT ROWID tables,
   may remain after rollback, and is connection state rather than a transaction
   receipt. Autocommit must query SQLite after failures instead of maintaining a
   guessed Boolean: the engine can automatically roll back on an error.
   Sources: [changes](https://www.sqlite.org/c3ref/changes.html),
   [rowid](https://www.sqlite.org/c3ref/last_insert_rowid.html),
   [autocommit](https://www.sqlite.org/c3ref/get_autocommit.html).

All native entries must validate owning thread/token before touching SQLite;
failed scalar outputs should be deterministic. Metadata queries must neither
step nor reset a statement. Extend regression coverage for stale/default/foreign
thread tokens, bounds/NUL, repeated names and sparse numeric parameters, metadata
before and after reset, duplicate aliases, rowid rollback semantics and engine
transaction recovery. Preserve checks and copied ownership while measuring cost.

**Next priority: transaction examples, then narrow configuration.** Existing
`execute` can already run `BEGIN DEFERRED/IMMEDIATE/EXCLUSIVE`, `COMMIT`,
`ROLLBACK`, `SAVEPOINT`, `ROLLBACK TO` and `RELEASE`. First document these with
checked failure recovery using autocommit. SAVEPOINT nesting does not imply
independent commits; ROLLBACK TO leaves the named savepoint active. Do not call
this RAII parity or add unsafe string interpolation of untrusted savepoint names.
A later convenience API should use fixed/validated identifiers or internal names
and report failed COMMIT/ROLLBACK distinctly. Source:
[SQLite savepoints](https://www.sqlite.org/lang_savepoint.html).

Read-only and bounded busy/work options already exist. A later, separately
reviewed option may request a small journal-mode enum such as preserve/default,
DELETE or WAL at open time. Apply only fixed SQL before installing the permanent
PRAGMA-denying authorizer, read and verify the returned effective mode, reject
unsupported/read-only changes and close on initialization failure. Do not silently
fall back, disable authorization for arbitrary caller SQL, weaken synchronous
settings, or claim work_budget bounds disk, heap or elapsed time. WAL is persistent
file configuration with checkpoint and sidecar behavior, not a Boolean performance
switch; read-only WAL needs appropriate existing sidecars/directory access or
other documented conditions. Do not add immutable URI support casually.
Sources: [WAL](https://www.sqlite.org/wal.html),
[durability settings](https://www.sqlite.org/pragma.html#pragma_synchronous),
[authorizer](https://www.sqlite.org/c3ref/set_authorizer.html),
[approximate progress callbacks](https://www.sqlite.org/c3ref/progress_handler.html).

**Explicit non-parity:** backup needs its own lifetime/error/busy protocol;
incremental BLOB I/O needs new resource tokens and transaction rules; UDFs need
safe callback/reentrancy/lifetime design; native extensions enlarge the trust
boundary. Rust/C++ RAII cannot be honestly equated with thread-exit cleanup or
block syntax; Goose has no destructors ([language README](https://github.com/aardappel/goose)).
This package's Linux x86-64 validation is not the portability coverage of CPython,
rusqlite or SQLiteCpp, and bundled engine deployment is a separate advantage of
the other Goose packages. None of these gaps is solved by the first expansion.
Do not advertise “same features or better” without naming the supported subset.

Follow CONTRIBUTING: independent design, implementation and final-validation
reviews; behavior regressions and required compiler/sanitizer checks; focused
Conventional Commits. This research makes no source changes or commits; the
implementing agent owns those reviews and validation.

## Fair performance comparison plan

The retained benchmark currently compares Goose with C calling the **same checked
adapter**, not raw SQLite or other wrappers. It includes process startup and
open/close. Keep those results under that description; they cannot establish an
alternatives ranking ([methodology](../bench/README.md)). No timing conclusions
follow from the feature matrix.

Use two explicitly labeled experimental groups:

* **Matched-policy wrapper comparison:** Goose production adapter, raw C with
  equivalent connection policy/state handling, Python, rusqlite and SQLiteCpp.
  Install equivalent defensive/trusted-schema/foreign-key/DQS settings, limits,
  authorizer and progress budget wherever public APIs or a disclosed test-only
  native setup bridge allow it. A bridge must configure policy, not replace a
  wrapper's timed binding/reading work. Record callback language: Python/Rust/C
  callback overhead is not interchangeable. If a control cannot be matched,
  disclose it per fixture and avoid claiming isolated wrapper overhead.
* **Native/default capability comparison:** separately report idiomatic wrapper
  defaults or vendored Goose packages, with actual policies/builds. This measures
  a different product configuration. Never combine it into the matched ranking.

Before accepting any comparable sample, establish that all dynamically linked
callers loaded the **same real SQLite shared object**: realpath and SHA-256,
version, source ID and compile options from each process. Disable rusqlite's
`bundled` features and SQLiteCpp's internal SQLite build (its
[build configuration](https://github.com/SRombauts/SQLiteCpp/blob/3.4.0/CMakeLists.txt)
provides `SQLITECPP_INTERNAL_SQLITE`); inspect Python's `_sqlite3` linkage too.
Matching version strings alone is insufficient. Vendored Goose alternatives need
an explicitly disclosed temporary experimental build or a separate group;
do not silently edit their production builds to manufacture equality.

Suggested fixtures, all deterministic and below the strictest package limits:

| Fixture | Timed operation and correctness evidence |
|---|---|
| Prepare cost | Prepare/step/read/finalize `SELECT 1` each iteration; verify count and sum. Separate from reuse fixture. |
| Reused scalar query | Prepare once, bind changing integer, step/read through DONE, reset; verify row count and sum. No accidental reprepare loop. |
| Reused text and blobs | Empty, 32 B, 4 KiB, 64 KiB text; empty, 4 KiB and large blobs. Bound value copy plus **owned output copy**, byte length and every byte verified, including NUL/NULL distinctions. Largest persisted values must leave room for row-encoding overhead under the 1 MiB limit. |
| Row scan | Same prebuilt table, projection, order and cardinality; stream rows, copy payloads and validate integer sum/count/byte totals. No fetch-all against streaming comparison. |
| Batched inserts | Same schema/indexes, prepared INSERT reused in one explicit transaction; time same BEGIN/COMMIT boundaries; verify count, sum and payloads after commit. |
| File durability | Separate rollback-journal and WAL groups, identical journal/synchronous mode, page size, timeout and checkpoint policy. Report commit/checkpoint time and effective settings; never compare WAL/NORMAL with DELETE/FULL as wrapper speed. |

Raw C/SQLiteCpp must explicitly copy borrowed column bytes; rusqlite must obtain
owned data rather than use ValueRef to avoid copying. Use copied bindings rather
than C SQLITE_STATIC/C++ bindNoCopy. Python text decoding and tuple allocation
are real language costs: specify valid UTF-8, optional text_factory choice and
any extra byte verification, without portraying Python as a no-copy interface.
For repeated SQL, Python offers cached execution rather than a public prepared
statement object: keep identical SQL and cached_statements enabled, disclose
execute/cache-lookup work. Similarly label Rust cached preparation versus holding
one Statement ([Python native connection/cache setup](https://github.com/python/cpython/blob/v3.15.2/Modules/_sqlite/connection.c),
[Rust cache](https://github.com/rusqlite/rusqlite/blob/v0.41.1/src/cache.rs)).

Use Python engine-autocommit mode (`autocommit=True` where available) and explicit
SQL BEGIN/COMMIT, rather than mixing legacy implicit DML transactions with the
other callers. Finish row-producing statements to DONE and inspect cleanup errors.
Use the same indexed lookup/query plans, seeds, paths/filesystem and database
contents. File fixtures must verify effective settings through a trusted harness
connection because this package denies PRAGMA. Distinguish shared warm OS cache
from deliberate cold-cache experiments and keep `:memory:` separate from files.

Primary times should be in-process monotonic measurements of a defined operation
region after interpreter/runtime startup, connection setup, fixture generation
and warmup. Report end-to-end startup/open/close separately if useful. Reusable
statement fixtures exclude prepare; the prepare fixture includes it. State whether
verification and output-buffer growth are inside the region and apply the same
rule to all callers. Retain per-sample correctness checks even when they add cost;
a failed checksum invalidates the sample. Use enough iterations to amortize clocks,
alternate/randomize caller order, record warmups and all repeats, report spread
and regressions rather than a best-only number. No unsupported universal ranking.

Offer configurable CPU affinity with an unpinned default or an explicit recorded
choice; never hard-code a CPU number or imply exclusive/fixed-frequency cores.
Retain raw JSON/CSV samples, failures and commands alongside source hashes,
wrapper tags/full revisions, Cargo.lock/features, compiler/interpreter versions,
optimization/assertion/LTO flags, Goose pin/cache controls, OS/kernel/architecture,
CPU model/governor/affinity/load, SQLite loaded-object hash/source ID/compile
options, database effective policies, fixture sizes, checksums, timestamps,
wall/CPU time and any RSS measurement method. This is the evidence needed for
independent review and reproduction, not a CI speed threshold.
