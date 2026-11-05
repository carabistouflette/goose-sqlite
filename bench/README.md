# Benchmarks

The benchmark records are measurements of named source snapshots. They do not
show that Goose is faster than another library in general. Read
[currentness and source limits](CURRENTNESS.md) before using any table.

## Run the basic caller comparison

The basic runner compares the checked Goose adapter with a checked C caller on
the same SQLite library. Both callers use the same SQL and connection settings.
The C caller is not unrestricted raw SQLite. The comparison includes caller,
builder, and foreign-call costs; it does not compare different database engines.

After setting up a Goose compiler, run:

```sh
make setup
make bench BENCH_ITERATIONS=10000
```

Or use an existing Goose compiler:

```sh
python3 bench/measure.py \
  --goose /path/to/goose \
  --iterations 10000 \
  --runs 3 \
  --output .build/bench-results
```

The runner builds both callers at `-O2`, while the production native adapter is
built by CMake in Release mode. It removes ambient compiler flags and gives Goose
a fresh temporary cache. Each fixture has a separate warmup; samples alternate
caller order. The JSON output records every sample, checksum, source and binary
hash, compiler and SQLite identity, machine, OS, affinity, and build flags.

Fixtures cover prepare/step/read, reused text and BLOB values, and inserts in one
transaction. Large values use fewer iterations. Timings include process startup,
setup, and cleanup. The runner verifies output bytes and insert results. Shared
host load, CPU frequency, and caches are not controlled; CPU affinity is not
exclusive isolation. CI has no timing threshold.

## Existing records

These reports retain their original raw samples and explain each workload,
units, warmups, repeats, results, spreads, and limitations. Their tables describe
the source and tools recorded with each run, not automatically the latest code.

- [Initial checked caller run](results/validated-2026-11-04/README.md)
- [Buffer reuse experiment](results/reuse-2026-11-04/README.md)
- [Other wrappers on one SQLite engine](results/alternatives-2026-11-04/README.md)
- [Scan, lookup, and batch workloads](results/workloads-2026-11-04/README.md)
- [Incremental BLOB reads](results/storage-2026-11-04/README.md)
- [Zero-filled BLOB binding](results/zeroblob-2026-11-05/README.md)
- [File-backed transactions](results/filebacked-2026-11-05/README.md)
- [Coordinated WAL reader/writer workload](results/mixedwal-2026-11-05/README.md)
- [Rejected row-cache experiment](results/row-cache-2026-11-04/README.md)
- [Rejected scan/copy experiment](results/scan-copy-2026-11-05/README.md)

Other runners have their own methods and reproduction commands:
[other wrappers](alternatives/README.md), [incremental storage](storage/README.md),
[zero-filled BLOB binding](zeroblob/README.md), [file-backed transactions](filebacked/README.md),
and [coordinated WAL readers and writers](mixedwal/README.md).
