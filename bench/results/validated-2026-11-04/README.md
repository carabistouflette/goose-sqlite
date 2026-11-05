# Initial benchmark evidence

> Historical source snapshot; these numbers are not current-source performance claims. See the [currentness audit](../../CURRENTNESS.md).

Recorded for clean source commit `9ec43742e4c2cb0841b36110433a41c1c22c79f3`.
[samples.json](samples.json) contains all 54 samples: nine fixtures, two callers,
three alternating-order passes. Ordinary fixtures use 100000 iterations, 64 KiB
text uses 10000 and 1 MiB BLOB uses 1000. Every sample passed its checksum and
value checks. All timings include process startup, connection setup and cleanup.

Goose compiler: exact GOOSE_REVISION and binary SHA256 in the record. Callers
use GCC -O2. Both link the same Goose-built CMake Release native adapter
(-O3/-DNDEBUG/-fPIC on this host), and runtime/build SQLite hashes match.
Runtime SQLite version, source ID and compile options are recorded, along with
native flags, all relevant source hashes, executables, CPU, OS and affinity.

This was a shared host, with other validation work occurring concurrently. CPU
frequency and scheduling were not controlled. There is no speed ranking or
statistical-significance claim. These are reproducible measurement fixtures and
an initial evidence record, not a claim of maximum possible performance. The
simple copied-byte interface remains unchanged pending workload-specific profiles.

Reproduce with `make bench BENCH_ITERATIONS=100000` after `make setup`; see
[methodology](../../README.md). Build directories and raw generated executables
are excluded from version control.
