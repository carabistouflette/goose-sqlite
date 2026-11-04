# Explicit initialization and WAL checkpoint validation

Final implementation/test source: cb0566c4c0ddf483ce4546a339d6fac4ab88742c.
Checks completed across 2026-11-04/05. These are finite correctness campaigns;
they are not performance measurements, a security certification or power-loss tests.

## Recovery matrix

| Configuration | Trials | Fault/crash points | Unsupported WAL groups | Acknowledged crashes |
|---|---:|---:|---:|---:|
| Host SQLite 3.54.1 / GCC adapter ASan/UBSan | 4678 | 4552 | 0 | 7 |
| Host SQLite 3.54.1 / Clang adapter ASan/UBSan | 4678 | 4552 | 0 | 7 |
| Pinned SQLite 3.54.1 / Clang engine+adapter ASan/UBSan | 4678 | 4552 | 0 | 7 |
| Minimum SQLite 3.37.0 / Clang adapter ASan/UBSan | 2934 | 2804 | 76 | 3 |

Total 16968 trials and 16460 fault/crash points, including 24 crashes after
acknowledged success. Each modern configuration has 268 checkpoint trials and
250 checkpoint fault/crash points. Minimum-engine checkpoint groups explicitly
skip because its WAL mode is unsupported. The original three workload counts
and coverage requirements are preserved independently.

Checkpoint first commits and verifies the complete new generation. Every error
or crash must preserve it. The test's idle anchor prevents last-close checkpointing
from substituting for the API. Fresh full-data/integrity checks and a successful
reopened-connection TRUNCATE checkpoint precede any application write.
Checkpoint hit trials per modern configuration: write 66, FULL 66, sync 4,
crash-write 33, crash-sync 2, read 66, truncate 4, SHM-lock 8, acknowledged crash 1.
Delete/SHM-map are genuinely unexercised by this scenario, and marked accordingly.
See [methodology](../../RECOVERY.md).

[recovery-summary.json](recovery-summary.json) retains original clean source
metadata, source/compiler/binary/engine hashes, engine identities, flags and
coverage. Every recorded source hash was verified against the full commit above.
The two canonical JSONL streams retain every trial, deduplicated by SHA-256 and
referenced from each configuration. Compiler identities were collected afterward
from unchanged build configurations. Earlier implementation runs are separate
from these final counts; no failed trial was discarded to obtain this record.

## Startup, checkpoints and public API

[validation.json](validation.json) binds final source and compiler/test logs.
Initialization allocation-failure tests reach two failing positions on each tested
engine, retry successfully **before any shutdown**, then open/close a usable
connection. Repeated successful initialization preserves live prepared handles
and ROW reads. It adds no cached failure state, extra mutex or public shutdown API.

Modern checkpoint native tests pass 12 checkpoints, five deterministic BUSY checks
and 12 transaction-state checks. This includes an independently held checkpoint
lock returning BUSY/-1/-1, old-reader partial progress, full payload integrity,
readonly/stale/foreign tokens, unaligned outputs, idle bindings and successful WAL
truncation. Native TSan executes the same competing-checkpoint synchronization.
Minimum-engine tests preserve fail-closed MISUSE with unavailable counts.

Public runner/native suites and isolated consumer imports pass on the system and
minimum engines. They exercise initialization, copied ownership, schema automatic
reprepare after expansion/shrinkage and checked checkpoint calls. The public file
suite uses a separate private file for each execution mode.

[threads.json](threads.json) retains host, pinned and minimum-engine concurrency
results. [wal-engine.json](wal-engine.json) and [tsan-engine.json](tsan-engine.json)
retain verified upstream checksums, actual flags and engine hashes. TSan first
requires an intentional-race probe to fail as expected, then requires clean thread
and checkpoint tests. It initializes the engine through production gq_initialize
before racing first registry/key use. Ordinary thread ASan/UBSan remains cold.
The [original cold-engine diagnostics](../concurrency-recovery-2026-11-04/README.md)
remain unresolved and are not recast as passing cold-start TSan results.

The rejected row-cache experiment and all 180 matched samples are retained
[separately](../../../bench/results/row-cache-2026-11-04/README.md). Production
getters/step are unchanged; the schema-reprepare regression tests remain.

## Limits

Checkpoint I/O has no hard page/time/memory bound. Counters are engine-sized;
BUSY can report partial progress or unavailable counts. The fixture preserves
OS cache and does not model torn writes, reordering, power loss or real disk
exhaustion. SHM unlock/unmap errors remain outside this campaign. All engine and
filesystem responsibilities in the API/security documentation still apply.

## Fuzzing and hosted CI

[fuzz.json](fuzz.json) and [fuzz.log](fuzz.log) retain a fresh-corpus 100000-input
ASan/UBSan/libFuzzer run, seed 219, max length 4096. The 11 initial tracked seeds,
final corpus manifest, source/binary/dictionary/engine hashes, flags and raw log
are preserved. The adapter is instrumented; that installed engine is not. Earlier
accumulated-corpus runs are separate from this reproducible fresh-seed record.

All native Ubuntu 24.04 x86-64/ARM64 and x86-64 TSan jobs passed the
[complete source validation](https://github.com/carabistouflette/goose-sqlite/actions/runs/41929243279).
[ci.json](ci.json) retains source/workflow/pin identities, architecture output,
job/step conclusions and relevant result excerpts. Both native jobs run public
runner/native/import tests, GCC/Clang sanitizers, pinned-engine positive WAL,
fuzzing and benchmark correctness smokes; TSan also runs checkpoint contention.
These correctness smokes establish no cross-architecture performance ranking.
