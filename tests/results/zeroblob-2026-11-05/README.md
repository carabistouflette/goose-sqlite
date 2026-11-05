# BLOB allocation errors and zero-filled binding validation

Implementation and final test source: `ead19309bef4394ffc041f079d50e2a8d78b7388`.
Checks completed on 2026-11-05. These finite correctness campaigns are not a
security certification or proof of freedom from memory errors.

## Correctness and allocation failures

[Validation](validation.json) binds source hashes, result counters and retained
logs. Native zero-BLOB tests verify 17 values, two foreign-thread rejections and
a 4096-byte explicit-transaction reservation/patch. Public runner/native suites
and isolated consumer imports pass on host SQLite 3.54.1 and minimum 3.37.0.
The [anonymous import](anonymous-import.log.gz) independently fetched the full
public implementation pin with global/system Git configuration and credential
prompts disabled, then passed both runner and native consumer modes.

The allocation-failure regression uses dynamic SQL-generated and directly bound
zeroblobs. All three getter paths (size, fetch, copy) reach an actual positive-size
materialization NOMEM for both sources on each tested engine. Failure outputs,
untouched buffers, cleanup and SQLite allocation baselines are checked. Lazy empty
BLOB reads preserve the BLOB type without materializing a pointer; live empty BLOB
and TEXT statements remain readable after another statement reports NOMEM.

The two `blob-oom-red*.log.gz` files retain development probes against the prior
published implementation: a positive lazy BLOB incorrectly returned OK/length 0
on materialization allocation failure. `empty-blob-red.log.gz` retains a later
development regression that caught zero-length materialization changing the type.
These are development diagnostics; the evolving probe harness did not have an
immutable standalone revision. Final committed regressions and passing results
are identified separately. The fix reads a strictly typed BLOB's byte count before
materialization, skips materialization for zero length, and reports NOMEM when a
positive-size BLOB cannot materialize. TEXT retains conversion-before-length order;
the fix does not depend on a possibly stale connection-wide error code.

## Recovery and concurrency

| Configuration | Trials | Fault/crash points | Unsupported WAL groups | Acknowledged crashes |
|---|---:|---:|---:|---:|
| Host SQLite 3.54.1 / GCC adapter ASan/UBSan | 4678 | 4552 | 0 | 7 |
| Host SQLite 3.54.1 / Clang adapter ASan/UBSan | 4678 | 4552 | 0 | 7 |
| Pinned SQLite 3.54.1 / Clang engine+adapter ASan/UBSan | 4678 | 4552 | 0 | 7 |
| Minimum SQLite 3.37.0 / Clang adapter ASan/UBSan | 2934 | 2804 | 76 | 3 |

Total: 16968 enumerated trials, 16460 fault/crash points and 24 process crashes
after acknowledged success. Trials include explicit unsupported-WAL skips.
[Recovery provenance](recovery-summary.json) retains source, binary, engine,
compiler and flag identities plus coverage. Every trial remains in two canonical
JSONL streams, deduplicated by SHA-256 and referenced by configuration. Compiler
identities were collected afterward from unchanged build configurations. The
[harness methodology](../../RECOVERY.md) covers full-data/integrity verification,
fresh recovery writes and checkpoint retries. Process death preserves OS cache;
this does not simulate power loss, torn writes or reordered I/O.

[Concurrency records](threads.json) cover independent thread-affine connections,
3072 unique tokens and 64 thread-exit cleanup callbacks per configuration.
Modern engines also require 256 committed rows and 160 reader snapshots.
Minimum-engine WAL groups skip explicitly. [Pinned ASan/UBSan](wal-engine.json)
and [TSan](tsan-engine.json) instrument both engine and adapter. TSan first detects
an intentional race in the [positive control](tsan-positive-control.log.gz), then
passes production thread/checkpoint/zero-BLOB checks after explicit serial engine
initialization. Ordinary ASan/UBSan thread tests retain concurrent cold startup.
The [original cold-engine TSan diagnostics](../concurrency-recovery-2026-11-04/README.md)
remain unresolved; no engine patch or sanitizer suppression was introduced.

## Fuzzing and hosted CI

[Fresh-corpus fuzz provenance](fuzz.json) and the [raw compressed log](fuzz.log.gz)
retain a 100000-input seed-219 ASan/UBSan/libFuzzer campaign with maximum input
length 4096. The 11 tracked initial seed hashes, final corpus manifest, compiler,
binary, source, dictionary, flags and installed engine hashes are recorded. No
failure artifact was produced. The adapter is instrumented; this installed SQLite
engine is not. The state model now includes zero-BLOB bindings and invalid lengths
and indices. It does not exhaust all SQL or operation/allocation sequences.

All three [hosted source-validation jobs](https://github.com/carabistouflette/goose-sqlite/actions/runs/41939789987)
passed at the full source pin: native Ubuntu 24.04 x86-64 and ARM64 plus scoped
x86-64 TSan. [CI evidence](ci.json) retains workflow/compiler pin, job and step
conclusions, architecture output and relevant result excerpts. Both native jobs
include the new public/native tests and six-path benchmark correctness smoke.
These checks do not measure cross-architecture performance.

## Evidence handling and limits

All recorded source hashes were verified against the full implementation commit
and unchanged working source bytes. Logs use deterministic gzip. The fuzz and
anonymous-import logs retain original bytes; other logs replace private checkout,
compiler and temporary-consumer prefixes with documented placeholders. Original
and retained uncompressed SHA-256 values are recorded. Original local process exit
statuses were not independently stored in this bundle except the separately
reported anonymous-import status; completion markers and hosted CI conclusions
provide the retained outcome evidence.

The zero-BLOB API has a 1 MiB input bound, not a hard heap, I/O or time budget.
Encoded persistent-row overhead can reject an accepted 1 MiB binding. Reading or
storing zero-filled BLOBs may allocate their full contents. Writable incremental
BLOB access requires an explicit transaction and bypasses SQL checks/triggers as
documented in the API. Performance and allocator-phase measurements are retained
[separately](../../../bench/results/zeroblob-2026-11-05/README.md).
