# Benchmark methodology

```sh
make setup
make bench BENCH_ITERATIONS=10000
# Or choose an existing pinned compiler:
python3 bench/measure.py --goose /path/to/goose --iterations 10000 --runs 3 --output .build/bench-results
```

Requires GCC (override BENCH_CC with a single compiler executable),
Python 3 and SQLite development files. The harness builds both callers at -O2, preserving assertions and the production
adapter's safety policies. Goose builds the native CMake target in its normal
Release configuration (-O3/-DNDEBUG on tested GCC). Both callers link that exact
static archive and the exact SQLite library found by CMake. The native source has
no assertions. A fresh temporary Goose cache excludes stale package options and
ambient CFLAGS/CXXFLAGS/CPPFLAGS/LDFLAGS are removed for these builds. No LTO or CPU-specific flags are added.

Nine fixtures: prepare/step/read/finalize SELECT 1; reused text binding/copy of
0, 32, 4096 and 65536 bytes; BLOB binding/copy of 0, 4096 and 1048576 bytes; and reused inserts inside one explicit transaction.
The largest text fixture uses one tenth the iteration count; the 1 MiB BLOB uses
one hundredth. Insert validation checks both row count and inserted-value sum. Every sample checks
its checksum; text workloads also check every copied byte against the input.
All fixtures include connection open and close. C output is initialized once to match the first Goose builder resize.
Successful reads reuse existing storage without clearing/reinitializing it; all
returned bytes are still copied and compared. Only a newly grown suffix needs
initialization in the Goose builder. Each executable gets a separate warmup;
recorded samples alternate execution order over three passes by default.

The C baseline calls the same checked production adapter. It is not unrestricted
raw SQLite and does not measure adapter overhead relative to raw SQLite. The
comparison helps identify Goose caller/builder/foreign-call overhead with matched
SQL and connection policies; allocation/runtime startup differs between languages.
It is not a ranking against other libraries or database engines.

samples.json records every whole-process wall and child user+system CPU sample,
source hashes, executable/compiler hashes, Goose revision, runtime SQLite version/source ID/compile options,
C compiler/flags, native CMake build type/flags/archive hash, build/runtime SQLite library hashes (required to match between callers),
hardware, OS, CPU affinity and source revision/dirty status.
Timing includes process startup, setup and cleanup; small runs are smoke tests,
not useful performance estimates. The host is shared, CPU frequency is not fixed,
and affinity does not imply exclusive cores. No timing thresholds in CI. Profile
an actual workload before changing the checked byte-copy path. Repeated outputs
that fit their current length use one bounded fetch; initial/growing outputs
report a required size and retry. Legacy native size/copy entry points remain
for compatibility.

Initial [raw measurement evidence](results/validated-2026-11-04/README.md) is retained
with all fixtures and provenance; see its limitations before interpreting timings.

The subsequent [buffer-reuse audit](results/reuse-2026-11-04/README.md) retains
matched before/after samples, instruction-profile summaries and a separate
current caller record. Successful getters now reuse their existing buffer;
only newly grown bytes are initialized before being overwritten. All failures
still clear logical output, and the native size/copy checks remain in place.

[Alternative wrappers](alternatives/README.md) now have a separate matched-engine,
in-process benchmark; it measures API paths with explicitly different safety policies.

## Incremental storage access

The [storage harness](storage/README.md) compares owned whole-column copies with
incremental ranges through Goose and raw SQLite C. The [retained results](results/storage-2026-11-04/README.md)
include both complete nine-round windows, known overlap, compiler/engine/source
provenance, checksums and every sample. It measures less data copied for partial
reads; full-value results and remaining wrapper overhead are reported too.
