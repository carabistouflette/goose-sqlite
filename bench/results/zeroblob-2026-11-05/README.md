# Zero-filled BLOB results

Implementation and benchmark source: `ead19309bef4394ffc041f079d50e2a8d78b7388` (clean).
All 270 timed samples, 30 allocator probes and 45 shuffled six-path rounds completed.
The shared-host CPU6 window lasted 43.734 seconds; affinity did not provide exclusive isolation.

## Timings

Median loop nanoseconds per operation; lower is faster. Every operation binds, steps,
copies owned output, verifies every byte, consumes DONE and resets. Lifecycle, input
buffer creation, output preallocation and same-statement priming are outside timing.

| Bytes | Goose copy | Goose zero binding | Goose SQL zero | C copy | C zero binding | C SQL zero |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 186.1 | 181.5 | 199.9 | 157.5 | 144.1 | 172.7 |
| 4096 | 2210.5 | 2222.2 | 2303.9 | 2236.6 | 2841.9 | 2254.3 |
| 65536 | 74304.0 | 75926.1 | 71536.2 | 77200.7 | 74204.0 | 72614.2 |
| 524288 | 702441.0 | 683125.1 | 720655.9 | 654665.7 | 688261.9 | 681234.5 |
| 1048576 | 1777260.8 | 1523908.3 | 1561807.1 | 1531730.2 | 1557157.3 | 1541465.3 |

Timing is mixed and sample spreads are wide. The new binding does not consistently
beat copied binding or the existing SQL function. These measurements establish no
universal speedup, disk-write ranking or statistically established regression.
All observed minima/maxima are retained in [summary.json](summary.json); they are
sample ranges, not confidence intervals. Table values are medians, not paired ratios.

## Binding allocation

For every nonzero size, copied binding increased SQLite allocator usage by exactly
its payload size. Both zero binding and existing `SELECT zeroblob(?1)` added zero
bytes at binding time, in raw C and the checked native ABI. Every probe subsequently
materialized and verified the entire value. Empty values added zero in all paths.
This is a compact binding representation available to alternatives too. Reading or
storing the value can allocate its contents later. The probes exclude input/output
malloc and the Goose heap; process RSS is separately recorded and includes setup.

## Provenance and reproduction

[samples.json](samples.json) contains every raw timing/checksum/stdout, all allocator
probes and metadata. [samples.jsonl](samples.jsonl) preserves incremental records;
[metadata.json](metadata.json) preserves standalone provenance. All relevant source
hashes were checked against the commit above. All three executables loaded the
same SQLite shared-object hash (3.54.1); engine source ID/options, tools, compiler
flags, binaries, generated caller, archive/header hashes, seed, ordering, host load
and timestamps are retained. Goose and C callers use GCC -O2; the native adapter
uses Release -O3/-DNDEBUG. Raw C and Goose retain different connection/safety policies.
Host: Linux x86-64, Intel Core Ultra 7 258V, powersave governor. No ARM timing claim.

```sh
python3 bench/zeroblob/measure.py --goose /path/to/pinned/goose \
  --iterations 32768 --runs 9 --cpu 6 --output .build/zeroblob-results
```

Choose an available core or omit affinity. See the [complete methodology](../../zeroblob/README.md)
for scaled iteration counts, checksums, warmup and allocator scope. This compares
six API paths on one engine; earlier cross-language results keep their original
source/version scope. It does not re-rank Python, Rust or C++ wrappers.
