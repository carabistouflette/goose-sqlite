# SQLite realistic workload comparisons

Ten fixtures, five callers, seven shuffled rounds: 350 checked samples in the final
[samples.json](samples.json), plus all 350 [before-registry.json](before-registry.json)
samples and 140 [matched registry samples](registry-matched.json). No fixture or
regressed pair was dropped. These are shared-host, nonexclusive CPU7 experiments;
CPU courtesy starts/completions were announced, not isolation guarantees. Process
UTC boundaries, affinity, OS, CPU, source/executable/archive/engine hashes, compiler versions and flags, and Goose/Rust compiler and GNU time hashes
are retained. Absolute times differ substantially between windows: **do not call
before-to-final median differences a controlled optimization effect**.

## Final median loop time, ns/operation

Scan is normalized per returned row; batch is per inserted row; other fixtures
are per query/bind/read/insert iteration. Scan processes 97 complete 1024-row passes
(99328 rows); ordinary fixtures use 100000 iterations, 64 KiB text uses 10000.

| Fixture | Goose | SQLite C API through C++ | SQLiteCpp | rusqlite | Python sqlite3 |
|---|---:|---:|---:|---:|---:|
| prepare | 1691.2 | 1514.7 | 1156.1 | 1162.5 | 3415.3 |
| scalar | 158.4 | 126.7 | 135.8 | 145.1 | 1423.7 |
| text32B | 225.9 | 175.2 | 209.0 | 246.5 | 1666.3 |
| text4KiB | 976.3 | 694.7 | 728.1 | 1212.5 | 3119.6 |
| text64KiB | 10067.0 | 7538.1 | 7474.9 | 56647.0 | 16449.0 |
| blob4KiB | 666.5 | 640.5 | 678.1 | 666.5 | 2276.6 |
| scalar insert | 252.3 | 230.8 | 237.4 | 246.2 | 849.1 |
| scan128B | 137.9 | 121.0 | 130.8 | 132.8 | 714.6 |
| lookup128B | 543.2 | 516.0 | 544.1 | 530.2 | 2202.8 |
| indexed batch128B | 1270.8 | 1269.4 | 1245.7 | 1280.0 | 2420.8 |

For the new workloads, Goose is close to native wrappers on indexed lookups and
indexed batches, while its scan path retains overhead versus the fastest C path.
It beats this Python path in all ten fixtures. It remains slower than the thin
native wrappers on several small/prepare/text paths. These are measured API paths,
not identical safety policies: Goose retains checked thread tokens, strict reads,
limits, authorizer and VM progress budget. Rust String text validates UTF-8; Goose
and C/C++ copy byte text. New BLOB fixtures reuse owned outputs in Goose/C/C++/Rust;
Python returns fresh immutable bytes. Existing seven fixtures keep their earlier
allocation behavior. No universal performance ranking follows.

## Final median whole-process peak RSS, MiB

This includes startup, setup and streaming verification, not just timed work.
It is GNU time's benchmark-child peak on Linux, with an approximate small native
pre-exec launch footprint. It is not incremental heap, PSS or SQLite allocator use.
The raw C API driver is written in C++ and includes its runtime; a different bare
C application can have a different baseline footprint. These figures establish
no universal per-binding memory advantage.

| Fixture | Goose | C API/C++ driver | SQLiteCpp | rusqlite | Python sqlite3 |
|---|---:|---:|---:|---:|---:|
| prepare | 3.70 | 5.52 | 5.62 | 4.16 | 12.35 |
| scalar | 3.70 | 5.68 | 5.68 | 4.16 | 12.39 |
| text32B | 3.80 | 5.64 | 5.61 | 4.16 | 12.37 |
| text4KiB | 3.91 | 5.58 | 5.66 | 4.17 | 12.39 |
| text64KiB | 4.04 | 5.89 | 5.86 | 4.36 | 12.61 |
| blob4KiB | 3.82 | 5.64 | 5.61 | 4.21 | 12.39 |
| scalar insert | 4.81 | 6.70 | 6.73 | 5.27 | 13.39 |
| scan128B | 4.01 | 5.82 | 5.86 | 4.36 | 12.52 |
| lookup128B | 3.93 | 5.89 | 5.85 | 4.33 | 12.52 |
| indexed batch128B | 19.94 | 21.64 | 21.61 | 20.29 | 28.52 |

The [launcher probe](rss-launcher-probe.json) and its [source](rss-launcher-probe.py)
validate the chosen accounting path. With 64 MiB touched in Python, direct wait4
reported 83936 KiB for /usr/bin/true; GNU time reported 1536 KiB. This catches the
inherited Python-parent RSS floor rather than treating it as target memory. The
same caveat about approximate accounting/native launch overhead remains. GNU time
version/hash is in every principal record.

## Matched registry optimization

A [Callgrind profile](registry-profile.json) of 100 native scan passes attributes
3.48% of whole-program instructions to pthread_getspecific and 1.23% to pthread_once.
This is instruction attribution, not wall-time attribution. The raw
[profile](registry-before.callgrind) and [annotation](registry-before-profile.txt)
replace only repository absolute paths with $REPO and retain hashes/commands.

The small registry cache avoids those repeated lookups while keeping pthread-key
cleanup ownership, every thread/token/generation check and copied ownership.
It publishes only after successful destructor registration and clears at destructor
entry, allowing trusted cleanup callbacks to create fresh registries safely.
A regression verifies stale old handles, functioning fresh handles, cleanup and
main-thread isolation. It passes on the original and optimized implementation.

The matched experiment interleaves seven pairs per fixture with the exact same
compiler/profile, runner source and SQLite object. Values below are paired
before/after loop-time ratios: above 1 favors the cache; below 1 is a regression.

| Fixture | Median paired ratio | Minimum–maximum |
|---|---:|---:|
| prepare | 1.008 | 0.885–1.085 |
| scalar | 1.075 | 1.007–1.084 |
| text32B | 1.057 | 0.982–1.100 |
| text4KiB | 1.024 | 0.829–1.320 |
| text64KiB | 1.007 | 0.914–1.104 |
| blob4KiB | 1.037 | 0.994–1.096 |
| scalar insert | 1.041 | 0.982–1.052 |
| scan128B | 1.065 | 0.949–1.097 |
| lookup128B | 0.989 | 0.904–1.210 |
| indexed batch128B | 1.031 | 0.931–1.122 |

Scalar reuse has median paired speed ratio 1.075 (about 7.0% lower paired loop time),
and scan 1.065 (about 6.1% lower paired loop time).
Indexed lookup is mixed/slightly slower by paired median (0.989), and several
other spans cross 1. All regressions and wide spreads remain visible. Native
executable code generation is the timing scope; the dynamic Goose runner passes
correctness tests but has no matching timing claim. The cache is retained for
its profiled reduction in repeated registry work and measured small-operation
benefit, not as an across-the-board speedup.

## Provenance and reproduction

Final source is clean e24de8ce7495c8146c6c9b408cf08686c981c182; baseline is clean
ccacd49c81b5e506ffb5c96d52d5771896b1d0a1. The matched after source is clean
443352f661ceb310ccf664e13e5c6982b5ecf4d4 with the identical final native archive
hash. The Goose runner/API counter work precedes both native optimization builds.
The native archive hashes agree between the matched candidate and final run.

All five callers load the same actual SQLite 3.54.1 object. Four emit runtime
version/source ID/options; Goose identity is inferred from the matching object.
The distribution alt1 source ID differs from upstream. Goose compiler is pinned
at eadca409f68210893f366e60d0c2f0dc29a339be; GCC callers use -O2, the native adapter
uses recorded Release -O3 -DNDEBUG, SQLiteCpp uses verified -O2 -DNDEBUG and external
SQLite, and Rust uses explicit opt-level 2 / Thin LTO / 16 codegen units / incremental with wrappers
disabled and resolved compiler identity. The measured Python is the installed
3.14.9, distinct from the reference release in the research document.

Source hashes/HEAD are captured before build and verified afterward. SQLiteCpp
must be clean at its pinned revision and uses fresh CMake configuration; actual
compiler/profile/engine settings and archive are recorded. An exploratory smoke
run caught a compiler-change cache reset that dropped optimization. It was fixed
before either principal series; it supplies no performance conclusion. An ambient
Rust compiler-cache incompatibility was likewise fixed before principal timing.

[Methodology/reproduction](../../alternatives/README.md) documents the ten fixtures,
SQL plans, setup/verification boundaries, owned-copy paths, tool requirements and
policy distinctions. Raw samples include process CPU/wall and peak RSS alongside
target monotonic clocks/checksums. EXPLAIN plans are verified through the controller's
shared engine; common plans across callers are an inference from matching schema,
SQL and engine, not independent introspection in every wrapper.
