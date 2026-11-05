# Coordinated finite WAL reader/writer comparison

Measured clean source: `8133274b6df6b63c27a3ef541a0539f1f7984d10`.
All **50 pairs, 6,400 successful writer commits and 69,359 checked reader snapshots**
passed, with five separate deterministic qualifications. Every pair observed all
four required intermediate committed-epoch bands, verified every final ID/epoch/
payload with an independent reopened oracle, passed integrity_check, and exited
cleanly. Neither role reported BEGIN-BUSY. There was one writer per pair, so this
is not evidence about writer contention, fairness, retry policies or saturation.

## Observed results

Goose's median checked-reader p50 was 17.02/17.17µs in the two orientations,
compared with raw C API 15.41/14.41µs, rusqlite 14.49/14.57µs, SQLiteCpp
16.92/15.34µs and Python 48.45/50.59µs. Goose's median writer commit p50 was
2.56/2.76ms. Writer rates, tails and relative order vary by caller and orientation.
These data support no universal ranking, isolated binding overhead, causal speedup
or statistically significant difference. No production optimization was made.

Each latency cell is the median of **five per-pair role quantiles**, in µs;
quantiles are not pooled across roles/pairs. All five callers are shown in fixed
order, including slower Goose results. Each writer quantile uses 128 successful
operations: nearest-rank p99 is the 127th value and excludes its single largest
operation. Reader observation counts vary, so reader tail resolution varies too.
Observed ranges, p95, maxima, rates, role windows, stop lags and separate RSS peaks
are retained in [summary.json](summary.json). Ranges are not confidence intervals.
The [interactive chart](report.html) switches orientation/metric and shows all
observed ranges. There is no combined-orientation rank.


### Writer CPU6, reader CPU7

| Caller | Read p50 µs | Read p99 µs | Commit p50 µs | Commit p99 µs | Writer commits/s | Coordinated snapshots/s |
|---|---:|---:|---:|---:|---:|---:|
| Goose | 17.02 | 96.24 | 2564.08 | 6084.16 | 303.56 | 3154.50 |
| Raw C API | 15.41 | 84.95 | 2747.26 | 6301.72 | 289.03 | 3037.62 |
| SQLiteCpp | 16.92 | 101.33 | 2893.73 | 11782.68 | 294.28 | 3032.71 |
| rusqlite | 14.49 | 97.27 | 2475.04 | 6319.36 | 325.72 | 3286.62 |
| Python | 48.45 | 136.22 | 2666.13 | 13057.86 | 278.72 | 2207.58 |

| Caller | Reader snapshots/pair min–max | Reader RSS median KiB | Writer RSS median KiB | Largest read µs | Largest commit µs |
|---|---:|---:|---:|---:|---:|
| Goose | 1132–1804 | 4528 | 4500 | 150.53 | 60073.54 |
| Raw C API | 1202–1592 | 6432 | 6436 | 154.99 | 50155.06 |
| SQLiteCpp | 1187–3656 | 6528 | 6532 | 176.26 | 145892.84 |
| rusqlite | 1026–1514 | 5036 | 4980 | 170.68 | 60516.28 |
| Python | 712–1427 | 15080 | 15116 | 208.19 | 66109.57 |

### Writer CPU7, reader CPU6

| Caller | Read p50 µs | Read p99 µs | Commit p50 µs | Commit p99 µs | Writer commits/s | Coordinated snapshots/s |
|---|---:|---:|---:|---:|---:|---:|
| Goose | 17.17 | 84.07 | 2760.73 | 10103.16 | 271.63 | 2927.98 |
| Raw C API | 14.41 | 82.91 | 2929.46 | 10162.70 | 268.39 | 3049.30 |
| SQLiteCpp | 15.34 | 74.49 | 2909.74 | 7370.20 | 276.97 | 3300.91 |
| rusqlite | 14.57 | 89.54 | 3086.74 | 13904.73 | 274.80 | 3115.44 |
| Python | 50.59 | 138.42 | 3347.28 | 14777.25 | 268.24 | 2065.30 |

| Caller | Reader snapshots/pair min–max | Reader RSS median KiB | Writer RSS median KiB | Largest read µs | Largest commit µs |
|---|---:|---:|---:|---:|---:|
| Goose | 1080–1473 | 4504 | 4512 | 141.86 | 62777.82 |
| Raw C API | 1149–1662 | 6432 | 6368 | 143.33 | 50932.10 |
| SQLiteCpp | 1196–1993 | 6464 | 6464 | 149.25 | 96483.08 |
| rusqlite | 1387–2006 | 4988 | 4940 | 143.75 | 105588.21 |
| Python | 989–1196 | 15028 | 15136 | 191.56 | 54137.61 |

Writer rates include streamed event formatting/flushing/bookkeeping. **COORDINATED
reader snapshots/s** additionally includes one parent command/wait per snapshot.
Operation clocks include SQL, result/change checks and copying/full-byte snapshot
verification, but exclude subsequent event logging. Different reader counts and
cadence create coupled implementation-pair workloads, not identical offered reader
load or isolated writer API overhead. Parent journals and raw role logs flush on
the same filesystem as the database and contribute I/O. No timing normalization,
clock subtraction between languages, outlier deletion or correction is applied.

RSS is GNU time's separate whole-lifetime reader or writer peak, including startup,
precomputed expected payload tables, setup, waits, verification and cleanup. These
peaks are not simultaneous: **never sum them** or interpret them as incremental
binding heap/PSS. C API uses a C++ driver and its runtime. Python/control-statement
caching, Goose prepare/finalize and safety limits, and C/C++ control/status checks
remain distinct paths, as documented in the [shared methodology](../../filebacked/README.md).

## Workload and correctness

Each fresh private WAL file has 32 rows with integer ID, epoch and 128-byte copied
binary payload. Payloads encode every epoch/ID, including NUL/0xff endpoints.
One reader and one writer process of the same implementation open independent
connections once. Every writer transaction updates all rows; every reader consumes
all rows, checks strict types, IDs, a common epoch and every owned payload byte.
Epochs never decrease. Reader work is finite and coordinated, with at most one
command in flight. All payload tables and matched semantic priming precede READY.

WAL, synchronous FULL(2), busy timeout0, page4096, cache_size=-2000, normal locking,
auto-checkpoint1000, foreign_keys1 and trusted_schema0 match. All five callers,
parent verifier/seeder and two-connection native probe used SQLite 3.54.1, object
SHA256 `99ad85c87b9c2a461a670a1db545ca17b29d9208fe4e2887a5ff6942f2c2e61a`.
SQLiteCpp 3.4.0 and rusqlite 0.41.1 pins, actual Python/Goose/toolchain/compiler
profiles, exact source/blob/generated/archive/executable/engine hashes and mapped
parent-engine proof remain in [metadata.json](metadata.json). Engine overrides
were empty. No alternate engine was used for principal measurements.

Goose policy is explicitly **inferred** from two simultaneous native connections
using the exact archive/options/engine. Its separate test-only probe verifies
PRAGMA denial before inspecting fixed settings; no public authorizer escape was
added. Other callers read their connection policy. Python exposes no NOMUTEX flag;
SQLiteCpp RAII cannot expose finalization/close status. No safety-policy equivalence
or general language ranking is asserted.

Five separate deterministic qualifications prove a held epoch-0 snapshot survives
an epoch-1 commit, a fresh reader sees1, uncommitted epoch 2 is invisible, rollback
restores 1, and independent final payload/integrity verification passes. The mixed
matrix is 10 shuffled rounds per caller (seed219), five per CPU orientation.
Prespecified gates require at least 96 successful commits, all 128 writer attempts,
all four intermediate reader progress bands, no unexpected errors, no cap/deadline
hit, both END markers/zero exits and exact independent final data. Actual commits
were 128 in every pair; all reader counts were 712–3656 under the 20,000 cap.
This proves useful interleaving, not exact continuous overlap.

The parent keeps an idle initialized WAL anchor until both workers exit; no
pending cursor/transaction is held. Final verification and pre/post file hashes
precede anchor cleanup. Last-close work is outside worker clocks. WAL length and
threshold 1000 do not establish peak size or causal checkpoint-tail coverage.
Files are warm in OS cache on Btrfs with compress=zstd:3/ssd mount options; fixed
payloads are compressible. Physical controller/durability and power-loss behavior
are unverified. This is not cold-cache or random-data storage evidence.

## Provenance, retention and validation

Principal recorder window: 2026-11-05T12:57:07.665053Z–2026-11-05T12:59:54.157809Z, including builds. Mixed-pair window: 2026-11-05T12:59:12.902697Z–2026-11-05T12:59:53.402800Z. CPU6/7 swapped roles; parent/build CPU5. Affinity is nonexclusive, governor powersave; package/core/thread fields are retained, unavailable hybrid identity remains unknown. Existing CONFIG compiler jobs were observed executing onCPU5/6/7 at12:58:32Z during builds, before the mixed-pair window. Shared-host load can continue to affect measurements; no exclusive-core claim or assumption that incidental work ended is made. Existing jobs were not interrupted.


[manifest.json](manifest.json) gives every container SHA256 plus each member's
original size/SHA256. Deterministic gzip/ustar headers normalize timestamps/owners;
**member bytes are unchanged**:

- [principal.tar.gz](principal.tar.gz): complete metadata, samples.json/JSONL,
  all 55 qualification/mixed pair results, event journals, raw stdout/stderr/RSS,
  and 31 frozen sources. No failed principal pair or automatic rerun occurred.
- [qualification.tar.gz](qualification.tar.gz): prior full-parameter development
  qualification (10 pairs+5 qualifications, same clean source), correctly smoke-labelled.
  All four bands were observed, though only this gate is relaxed in smoke.
- [ci-smoke.tar.gz](ci-smoke.tar.gz): local positive-WAL smoke using the separately
  checksum-verified normal test engine; correctness evidence, not timing results.
- [development-incomplete.tar.gz](development-incomplete.tar.gz): earlier development
  smoke rejected after source/CI edits during recording. It remains incomplete;
  its 10 streamed pairs are excluded from principal data. It was not a principal
  performance rerun.

Successful databases/sidecars were independently checked/hashed before removal;
logical and file hashes remain. Build binaries/caches are excluded from containers;
their recorded identities remain in metadata. Archives contain private fixture
paths normalized to $BUILD/$SOURCE, not reusable application databases. Extract a
container into a new directory and verify member hashes before analysis.

Two independent final actor/controller reviews cleared the frozen source after
fixes for Rust redundant timed checks, semantic priming, Python command handling,
broken-pipe cleanup, timeout ownership and topology provenance. Malformed-protocol,
all-BUSY commit-floor and actual OS broken-pipe probes were separately checked.
Exact-source CI 42029462705 passed x86-64, native ARM64 and scoped TSan jobs, including
positive-WAL mixed smoke on both architectures. No ARM performance comparison or
new cold-engine race guarantee follows; the unresolved cold-engine TSan and
serialized-engine-initialization limitation remain unchanged. Production library,
native sources, manifest, CMake and compiler pin remain byte-identical to 8a1d0d7.

```sh
# Principal recording; requires the pinned compiler/cache/dependencies.
env -u LD_LIBRARY_PATH -u LD_PRELOAD -u LD_AUDIT /usr/bin/python3 \
  bench/mixedwal/measure.py --goose /path/to/pinned/goose \
  --attempts 128 --rows 32 --read-cap 20000 --rounds 10 \
  --writer-cpu 6 --reader-cpu 7 --coordinator-cpu 5 \
  --output .build/mixedwal-principal
# Rebuild the summary/containers into a NEW output directory.
python3 bench/mixedwal/summarize.py --principal .build/mixedwal-principal \
  --qualification .build/mixedwal-full-qualification \
  --ci-smoke .build/mixedwal-ci-final-smoke \
  --development-failure .build/mixedwal-harness-agent-smoke-final \
  --output .build/mixedwal-derived
python3 bench/mixedwal/report.py .build/mixedwal-derived
```

The recorder rejects dirty/changed principal source, nonempty loader overrides,
wrong policy/engine/epoch/payload/protocol, cap/deadline exhaustion and unexpected
SQLite errors. [CONTRACT](../../mixedwal/CONTRACT.md) and
[methodology](../../mixedwal/README.md) define finite bounds and metric scope.

