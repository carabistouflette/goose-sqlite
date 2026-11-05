# File-backed transaction and BUSY comparison

Measured clean source: `52dca0d4f3d5718b5f7c4c586249d7404c80f783`.
All 270 process samples, 34560 operation latencies and 30 separate warmups passed.
Each sample contains 128 transactions/attempts; commit/rollback transactions have
16 inserts of a copied128-byte binary payload. Outcomes and every final ID/payload
were independently verified after reopening, with integrity_check=ok.

## Results

The tables compare measured API paths on one engine and host. They establish no
universal library ranking or statistically significant difference. Commit medians
cluster across callers; the tail and throughput results vary. Every case is shown,
including unfavorable Goose results. No production optimization was made.

Each latency table cell is the median of nine **per-process** quantiles, in µs.
A process quantile uses 128 observations; nearest-rank p99 is the127th value and
excludes the single largest operation. Maximum observations are shown separately.
Quantile ranges, throughput/RSS spreads and all raw vectors remain in
[summary.json](summary.json) and [samples.json](samples.json). Min/max ranges
are observed sample ranges, not confidence intervals.

### Median per-process p50 latency (µs)

| Case | Goose | Raw C API | SQLiteCpp | rusqlite | Python |
|---|---:|---:|---:|---:|---:|
| DELETE commit | 12498.62 | 12515.53 | 12737.61 | 12692.06 | 12517.05 |
| DELETE rollback | 110.51 | 105.38 | 107.94 | 105.41 | 142.35 |
| DELETE busy | 4.48 | 4.16 | 4.09 | 4.37 | 7.02 |
| WAL commit | 3300.74 | 3387.42 | 3324.14 | 3403.20 | 3484.37 |
| WAL rollback | 12.41 | 11.21 | 11.28 | 11.70 | 35.47 |
| WAL busy | 1.35 | 1.04 | 1.06 | 1.32 | 3.30 |

### Median per-process p99 latency (µs)

| Case | Goose | Raw C API | SQLiteCpp | rusqlite | Python |
|---|---:|---:|---:|---:|---:|
| DELETE commit | 29831.68 | 27626.90 | 22650.87 | 40160.45 | 24086.32 |
| DELETE rollback | 3229.99 | 3204.72 | 3107.74 | 3281.43 | 3240.38 |
| DELETE busy | 16.49 | 17.59 | 15.60 | 6.60 | 43.36 |
| WAL commit | 10054.65 | 6487.11 | 6516.41 | 6906.53 | 7135.19 |
| WAL rollback | 36.23 | 41.60 | 48.33 | 38.42 | 1514.60 |
| WAL busy | 6.06 | 2.24 | 1.90 | 3.21 | 16.07 |

### Largest observed operation (µs)

| Case | Goose | Raw C API | SQLiteCpp | rusqlite | Python |
|---|---:|---:|---:|---:|---:|
| DELETE commit | 106169.10 | 248643.87 | 73329.36 | 105017.95 | 530330.81 |
| DELETE rollback | 6164.48 | 6902.80 | 5887.54 | 6206.36 | 6210.51 |
| DELETE busy | 3015.59 | 2883.00 | 5080.10 | 3323.50 | 3961.19 |
| WAL commit | 144041.19 | 33866.22 | 13619.95 | 19034.15 | 88840.72 |
| WAL rollback | 3307.05 | 3293.59 | 2964.23 | 3293.81 | 3017.55 |
| WAL busy | 2187.38 | 2134.33 | 1828.22 | 3239.56 | 1028.05 |

### Median whole-child peak RSS (KiB)

| Case | Goose | Raw C API | SQLiteCpp | rusqlite | Python |
|---|---:|---:|---:|---:|---:|
| DELETE commit | 4272.00 | 6248.00 | 6336.00 | 4712.00 | 13008.00 |
| DELETE rollback | 4008.00 | 5976.00 | 5956.00 | 4408.00 | 12708.00 |
| DELETE busy | 4172.00 | 6156.00 | 6204.00 | 4580.00 | 12880.00 |
| WAL commit | 4316.00 | 6240.00 | 6348.00 | 4632.00 | 13000.00 |
| WAL rollback | 4052.00 | 5976.00 | 6020.00 | 4476.00 | 12720.00 |
| WAL busy | 4136.00 | 6040.00 | 6164.00 | 4572.00 | 12904.00 |

### Median loop throughput (case-specific units)

| Case | Goose | Raw C API | SQLiteCpp | rusqlite | Python |
|---|---:|---:|---:|---:|---:|
| DELETE commit | 1174.79 | 1181.12 | 1229.18 | 1183.67 | 1160.37 |
| DELETE rollback | 3739.69 | 3813.39 | 3665.98 | 3766.79 | 2997.65 |
| DELETE busy | 207537.17 | 191041.35 | 200221.18 | 217851.95 | 31984.60 |
| WAL commit | 4271.72 | 4499.80 | 4623.37 | 4550.89 | 4017.04 |
| WAL rollback | 27778.56 | 29653.37 | 50202.69 | 35650.02 | 13823.97 |
| WAL busy | 643714.23 | 849290.71 | 811533.93 | 605183.78 | 213680.92 |

Commit throughput is **committed rows/s**; rollback is **rolled-back transactions/s**;
BUSY is **rejected attempts/s**. These units must not be combined into a ranking.
Per-operation quantiles and enclosing-loop throughput answer different questions;
outliers and loop bookkeeping can change their order. No causal attribution or
timing correction is applied. RSS includes setup, runtime, verification and cleanup,
including two connections in BUSY; it is not incremental binding heap or PSS.
The raw C API driver is C++ and includes that runtime footprint.

## Workload, policy and scope

Fresh private files use DELETE or WAL, 4096-byte pages, synchronous FULL, busy timeout 0,
normal locking, cache_size=-2000 and auto-checkpoint 1000. Foreign keys are enabled
and trusted_schema is disabled. All five callers and the native probe load the
same SQLite 3.54.1 shared-object SHA256. Other safety/allocator/control-SQL policies
remain different: Python caches control SQL; Goose prepares/finalizes execute;
C/C++ controls/status use raw C; SQLiteCpp row operations use its public API and
RAII cannot expose finalization/close status. Python exposes no NOMUTEX option.

Goose policy is explicitly **inferred** from two simultaneous connections in a
separate probe using the exact native archive, engine and options. The probe checks
PRAGMA denial before test-only authorizer removal for fixed reads. It is not linked
into the production package, and no public policy escape was added.

Commit and rollback counters count only timed transactions. Every inserted row
must affect exactly one row, including rollback workloads. BUSY holds another
connection’s write lock for every measured BEGIN IMMEDIATE, checks actual BUSY
codes and autocommit, then releases the blocker and commits successfully on the
same contender outside timing. This is rejection latency, not concurrent-writer
throughput, fairness, timeout waiting or a retry policy. There are no application-level retries; the recorded automatic_retries field refers to application retry loops.

Operation clocks include SQL/error/change-count/autocommit checks; the outer loop
also includes recording/bookkeeping. Setup, priming, full verification and closure
are outside the loop clock. Last-close WAL checkpoint work can therefore be outside
loop timing while included in whole-process measurements. Seed WAL is truncated
and closed before each child; initial WAL is absent/empty. We retain the 1000-page
threshold and observable file sizes, but post-close files do not establish peak WAL
size or auto-checkpoint-tail coverage. No deliberate threshold-crossing case is claimed.

Files are warm in OS cache on this host’s Btrfs mount, with compress=zstd:3 and ssd
mount options. Physical storage/controller behavior is unverified. Fixed payloads
are highly compressible; this is not a random-data, cold-cache, physical-disk or
power-loss comparison. CPU6 affinity, powersave governor and shared-host loads are
recorded; no exclusive isolation or fixed frequency. All results/spreads are retained.

## Provenance, validation and reproduction

Principal parent window: 2026-11-05T08:09:40.674484Z–08:13:09.327117Z (208.652632886s,
including builds). Measured-child window:08:10:53.628397Z–08:13:08.958116Z. CPU6 was
released after the normal complete run. [metadata.json](metadata.json) retains
actual compiler/interpreter/dependency profiles, generated code/archive/binary hashes,
source/workflow/compiler pin, engine identity/options and parent mapped-object proof,
filesystem, tools, timestamps, order, checksums and completion state.

[samples.jsonl](samples.jsonl) preserves every flushed principal record; [samples.json](samples.json)
also includes warmups and all metadata. Files are copied unchanged. Successful fixture
databases were fully checked and hashed, then removed; their logical/file hashes remain.
Failed fixtures would be retained; none failed in the principal series.

Independent design, runner and recorder reviews informed the implementation. Duplicate
Rust change-count work and avoidable Python/C++ dispatch/timer bookkeeping were corrected
before principal recording. Source hashes are verified against Git and frozen bytes.
Actual parent/child/probe engine hashes match; nonempty loader overrides are rejected.
Bad policy/count/negative-code/payload cases were separately rejected. Early smoke
records are development checks, not included in these 270 principal samples. Hosted
CI uses DELETE-only benchmark smoke on older packaged engines; the separate pinned
engine tests retain positive WAL coverage and existing serialized-startup TSan scope.

```sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD -u LD_AUDIT /usr/bin/python3 \
  bench/filebacked/measure.py --goose /path/to/pinned/goose \
  --transactions 128 --batch 16 --runs 9 --cpu 6 \
  --output .build/filebacked-results
```

Choose an available/coordinated core or omit affinity. See [the full methodology](../../filebacked/README.md).
Existing in-memory results retain their original source/version scope. The library’s
production/native/build/compiler bytes remain unchanged from 8a1d0d7; original
cold-engine TSan diagnostics remain unresolved. These benchmarks are not a security certification.

Caller order was shuffled within each fixed journal/workload block. Blocks
themselves were not interleaved or randomized; journal-mode contrasts are
observational and do not establish a causal WAL-versus-DELETE speed difference.
FULL is the matched configured policy, not a promise of identical power-loss
behavior across journal modes or storage devices. Reproduction requires
Python 3.11+ for the recorder (tomllib), alongside the listed native toolchains.
