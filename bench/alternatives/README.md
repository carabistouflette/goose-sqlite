# Alternative SQLite API paths

```sh
make setup
python3 bench/alternatives/measure.py --goose .toolchain/goose/build/goose --iterations 100000 --runs 7 --cpu 7 --output .build/alternative-results
```

Requires Python 3, Git/network access for the exact SQLiteCpp source commit,
CMake, GCC/G++, Cargo/Rust and system SQLite headers/library. Cargo.lock fixes
Rust dependency resolution; no bundled SQLite feature is enabled. Dependencies
remain in ignored build/target directories, not vendored into the library.
Omit --cpu for unpinned execution; coordinate any selected core before timing.

Five callers: Goose, direct SQLite C API through a small C++ driver, SQLiteCpp
3.4.0 at df0a28ca9733f687ab7ce77f070c0df84368a45e, rusqlite 0.41.1, and the
installed Python sqlite3. The research/reference Python version is distinct from
the measured interpreter. Every executable/module must load the exact same
SQLite shared-library hash; version, source ID and compile options must match.
The direct C API baseline is not the old checked-adapter C baseline.

Seven fixtures use the same SQL/ASCII/byte inputs and iteration counts: uncached
prepare SELECT1; reused scalar bind/read; copied text at32B/4KiB/64KiB; copied4KiB
BLOB; and reused inserts inside one explicit in-memory transaction. Text/blob
outputs own their storage; every byte is compared inside the timed loop. Scalar
queries verify each value and total sum. All SELECTs consume DONE. Insert schema
and prepared statement setup precede timing; BEGIN/COMMIT are inside, sum/count
validation follows. Largest text uses one tenth of the requested iterations.

Primary loop wall times use each language's monotonic clock, excluding process
startup, open, fixture generation and reusable preparation. Whole-process wall
and child CPU times are retained separately. Each executable gets an untimed
warmup process; each measured sample is a new process/connection, with the warmup
not reusing its statement cache. Seven orders are deterministically shuffled with
seed219, retaining every sample and checksum. There are no timing CI thresholds.

This compares ordinary checked API paths, NOT identical safety policies or
query engines. Goose retains strict typed reads, copied ownership, TLS token
validation, defensive/trusted-schema settings, fixed limits, authorizer and
progress budget. The other wrappers use their ordinary policies with1000ms busy
timeouts. Raw C, SQLiteCpp and Rust select NOMUTEX/private-cache like Goose;
Python exposes neither connection mutex flags nor a held prepared statement.
Python prepare disables caching; other fixtures use its SQL cache and cursor
execute, with normal Unicode text decoding. Rust holds a Statement, consumes Rows
through reset and explicitly finalizes. SQLiteCpp uses prepare_v2 and RAII cleanup;
its destructors do not expose finalization status. Goose/raw C use persistent
prepare_v3. Raw C/C++ copy byte outputs into std::string; Rust allocates owned
String/Vec, Python returns owned str/bytes, while Goose reuses a caller builder.
Those API/allocator differences remain measured and are not hidden parity claims.

Only in-memory workloads are measured here. No filesystem, WAL, cold-cache,
checkpoint, durability, contention, portability, UDF or backup ranking follows.
The other Goose bindings in docs/alternatives.md have separately bundled engine
builds/policies; their advertised features are inspected, not timed in this matched
shared-engine group. A bundled-engine comparison would be a separate experiment.

Raw JSON records toolchains/interpreter, wrapper pins, source/binary hashes,
SQLite identities/library hashes, build flags, CPU/OS/affinity, order and all
loop/whole-process samples. Shared-host load/frequency are uncontrolled; affinity
is not exclusive isolation or statistical significance. Interpret all fixtures,
including regressions; do not select only the fastest result.
