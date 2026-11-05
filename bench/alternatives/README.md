# Alternative SQLite API paths

```sh
make setup
python3 bench/alternatives/measure.py --goose .toolchain/goose/build/goose --iterations 100000 --runs 7 --cpu 7 --output .build/alternative-results
```

Requires Python 3, GNU time, Git/network access for the exact SQLiteCpp source commit,
CMake, GCC/G++, Cargo/Rust and system SQLite headers/library. Cargo.lock fixes
Rust dependency resolution; no bundled SQLite feature is enabled. Dependencies
remain in ignored build/target directories, not vendored into the library.
Omit --cpu for unpinned execution; coordinate any selected core before timing.

Five callers: Goose, direct SQLite C API through a small C++ driver, SQLiteCpp
3.4.0 at df0a28ca9733f687ab7ce77f070c0df84368a45e, rusqlite 0.41.1, and the
installed Python sqlite3. The research/reference Python version is distinct from
the measured interpreter. Every executable/module must load the exact same
SQLite shared-library hash. Four alternatives explicitly emit version/source ID/
compile options; Goose's identity is inferred from its identical loaded library.
The direct C API baseline is not the old checked-adapter C baseline.

The original seven fixtures use the same SQL/ASCII/byte inputs and iteration counts: uncached
prepare SELECT1; reused scalar bind/read; copied text at32B/4KiB/64KiB; copied4KiB
BLOB; and reused inserts inside one explicit in-memory transaction. Text/blob
outputs own their storage; every byte is compared inside the timed loop. Scalar
queries verify each value and total sum. All timed SELECT fixtures consume DONE; untimed aggregate validation uses each
API's single-row query/read path. Insert schema
and prepared statement setup precede timing; BEGIN/COMMIT are inside, sum/count
validation follows. Largest text uses one tenth of the requested iterations.

Primary loop wall times use each language's monotonic clock, excluding process
startup, open, fixture generation and reusable preparation. Whole-process wall
and child CPU times are retained separately. Each executable gets an untimed
warmup process; each measured sample is a new process/connection, with the warmup
not reusing its statement cache. Seven orders are deterministically shuffled with
seed219, retaining every sample and checksum. Reusable preparation is primed inside each
measured process before its clock starts. There are no timing CI thresholds.

This compares ordinary checked API paths, NOT identical safety policies or
query engines. Goose retains strict typed reads, copied ownership, TLS token
validation, defensive/trusted-schema settings, fixed limits, authorizer and
progress budget (explicitly 100000000 instructions per call for aggregate
verification, above its normal1000000 default). The other wrappers use their ordinary policies with1000ms busy
timeouts. Raw C, SQLiteCpp and Rust select NOMUTEX/private-cache like Goose;
Python exposes neither connection mutex flags nor a held prepared statement.
Python prepare disables caching; other fixtures use its SQL cache and cursor
execute, with normal Unicode text decoding. Reusable Python SQL is primed on the same
connection before timing; insert priming is rolled back. Python runs with -I so
PYTHONOPTIMIZE cannot remove validation or DONE-fetch work. Rust holds a Statement, consumes Rows
through reset and explicitly finalizes. SQLiteCpp uses prepare_v2 and RAII cleanup;
its destructors do not expose finalization status. The shared C/C++ driver uses
raw sqlite3_exec for setup and BEGIN/COMMIT; timed row operations use the public
SQLiteCpp Statement/Column interface. Goose/raw C use persistent
prepare_v3. Raw C/C++ copy byte outputs into std::string; Rust allocates owned
String/Vec (String validates UTF-8), Python returns owned str/bytes, while Goose reuses a caller builder.
Those API/allocator differences remain measured and are not hidden parity claims.

Only in-memory workloads are measured here. No filesystem, WAL, cold-cache,
checkpoint, durability, contention, portability, UDF or backup ranking follows.
The other Goose bindings in docs/alternatives.md have separately bundled engine
builds/policies; their advertised features are inspected, not timed in this matched
shared-engine group. A bundled-engine comparison would be a separate experiment.

Builds use an explicit Rust host/target directory and clear ambient release/
Rust flag overrides. Explicit Rust profile options fix opt-level2, Thin LTO,
16 codegen units and incremental compilation; Goose uses a fresh package cache. CMake general C++ flags
are explicitly reset. Raw JSON records toolchains/interpreter, wrapper pins, source/binary hashes,
SQLite identities/library hashes, build flags, CPU/OS/affinity, order and all
loop/whole-process samples. Shared-host load/frequency are uncontrolled; affinity
is not exclusive isolation or statistical significance. Interpret all fixtures,
including regressions; do not select only the fastest result. samples.jsonl is
flushed after each successful sample; subprocess failures create failure.json.
An initial500000-iteration series hit Goose's default VM limit during untimed
aggregate verification and produced no complete published result; the maintained
runner now requests the documented larger budget before comparison.

The first two retained datasets were built before the harness learned to force
that profile: user Cargo configuration already enabled Thin LTO and incremental
compilation, overriding the original manifest. Their raw lto=false metadata was
incorrect. The published results include an explicit erratum rather than silently
rewriting those records. The corrected harness enforces the observed profile for
future comparisons. See the results README before interpreting any raw record.

## Extended workload and memory series

The maintained harness now includes three additional fixtures (ten total):

- `scan`: 1024 fixed rows per complete pass, ordered by integer primary key, with
  ID and owned 128-byte BLOB copied/verified for every row. Requested iterations
  are divided by 1024 (minimum one pass); `operations` records actual returned rows.
- `lookup`: a reused primary-key lookup for `(iteration*17)%1024`, verifying the
  returned ID and all owned 128-byte BLOB bytes, then consuming DONE/reset.
- `batch`: INSERT with integer primary key, a secondary group index and 128-byte
  BLOB bound/copied each time, inside one explicit transaction. Full ID/group/BLOB
  verification streams after timing; BEGIN/COMMIT are timed. No fetch-all lists.

Binary payloads contain NUL and 0xff. New C/C++ string buffers, Rust Vec and Goose
builders reuse owned output capacity; Rust borrows a ValueRef only long enough
to copy into its owned buffer. Python's sqlite3 returns fresh immutable bytes.
This differs from the older text/BLOB fixtures' allocation strategies, which
remain unchanged. Python primes its SQL cache outside timing. Other callers hold
prepared statements. SQLite C and SQLiteCpp BEGIN/COMMIT/setup still use raw exec
as disclosed above. A shared-engine Python EXPLAIN preflight retains the intended
scan/primary-key plans; inference across callers relies on identical schema/SQL
and the verified common engine, not separate plan introspection in every wrapper.

GNU `/usr/bin/time` is additionally required (Ubuntu package `time`). The harness
records `%M` as benchmark-child whole-lifetime peak RSS in KiB on Linux, including
startup, setup and verification. GNU time starts the target from a small native
image, avoiding direct Python wait4 accounting's inherited-parent RSS floor.
Its small native pre-exec launch footprint can still be part of the peak. This
is not timed-loop-only memory, incremental allocation, private/PSS memory or total
SQLite allocator usage. A peak may occur outside the timed region even though
all callers stream validation. OS RSS accounting is approximate; retain spreads.
Whole-process wall/CPU clocks include launcher overhead; target loop clocks do not.
The GNU time version/hash is retained. This does not establish a universal memory
ranking, particularly against a raw C API baseline implemented by a C++ driver.

Source HEAD/hashes are captured before build and checked again after timing;
changes reject the series. Cached SQLiteCpp must be clean at the exact revision,
uses fresh CMake configuration, and its actual Release flags, external-engine
setting, compiler and archive hash are recorded. This prevents cache reset from
silently dropping optimization when compiler selection changes. Rust uses the
resolved recorded compiler, explicit profile and disabled compiler wrappers.
Goose's actual native compiler/flags/archive are retained too. Shared engine
hashes are checked before and after the series. Principal data uses a clean
measured commit. An exploratory smoke run exposed a cache-reset O0 build; it
was corrected before principal timings and supplies no performance conclusions.

The [frozen instruction profiler](profile.py) uses the same checked native Goose
runner for scan, lookup and text-copy attribution. [Retained profiles](../results/scan-copy-2026-11-05/README.md)
include a rejected equal-length-resize experiment. Callgrind output is not native
timing; production scan/copy behavior remains unchanged.
