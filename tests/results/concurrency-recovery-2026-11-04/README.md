# Concurrent connection and expanded recovery validation

Final test source: 4a7e36368f25a00bb9a0ab722043aa2d2a642c67. These are finite
correctness checks, not performance measurements or a safety certification.

## Recovery

| Configuration | Trials | Fault/crash points | Unsupported WAL groups | Acknowledged crashes |
|---|---:|---:|---:|---:|
| Host SQLite 3.54.1 / GCC adapter ASan/UBSan | 4410 | 4302 | 0 | 6 |
| Host SQLite 3.54.1 / Clang adapter ASan/UBSan | 4410 | 4302 | 0 | 6 |
| Pinned SQLite 3.54.1 / Clang engine+adapter ASan/UBSan | 4410 | 4302 | 0 | 6 |
| Minimum SQLite 3.37.0 / Clang adapter ASan/UBSan | 2915 | 2804 | 57 | 3 |

Total 16145 trials, 15710 fault/crash points and 21 acknowledged crashes passed.
Every row/BLOB/padding byte and integrity check passed; backup sources stayed
unchanged. A successful acknowledged operation requires the complete new state.
Unacknowledged errors/crashes permit a complete old or new state; truncate errors
can leave the complete new state. Mixed/partial states always fail.

On each modern-engine run, added-kind hit trials were read 814, truncate 2,
delete 6, SHM-map 12 and SHM-lock 60, covering both one-shot and persistent failures.
Some workloads do not invoke a particular method; these groups are explicitly
unexercised. SHM unlock/unmap, torn writes, reordering, power loss and real disk
exhaustion remain outside this model. See [methodology](../../RECOVERY.md).

[recovery-summary.json](recovery-summary.json) retains original source-commit and
dirty-state metadata, hashes, engine identities, compiler hashes/versions and
coverage. Every recorded test/adapter/driver/CMake source hash was additionally
verified against 4a7e363. The minimum-engine run used identical final source before
its commit; its original dirty metadata is preserved. Compiler identities were
collected after completion from unchanged build configurations. Two canonical
record streams retain every trial, deduplicated by SHA-256 and referenced by each
configuration. Earlier development runs are separate from these final counts.

## Concurrent connections

[threads.json](threads.json) records host GCC/Clang, pinned ASan/UBSan and TSan,
and minimum-engine runs. Each passed 3072 unique tokens and 64 thread-exit cleanup
callbacks with rollback and destructor reentry. Each positive WAL run passed 256
committed rows and at least 160 full reader snapshots. SQLite 3.37 explicitly skips
WAL and reports zero WAL writes/snapshots. Cold engine initialization is concurrent
in ordinary runs; only TSan explicitly serializes engine initialization.

[wal-engine.json](wal-engine.json) and [tsan-engine.json](tsan-engine.json) retain
the verified SQLite archive/source checksums, compiler/flags and engine hash.
The TSan positive control must detect a deliberately racy test program before
stress starts; [its diagnostic](tsan-positive-control.log) is an expected failure.
The subsequent scoped stress exits successfully with no sanitizer diagnostics.

The first cold-start TSan attempts failed inside pristine SQLite 3.54.1:
[local diagnostic](tsan-cold-local.log) reports the isInit fast path, and
[hosted diagnostic](tsan-cold-hosted.log) reports sqlite3MutexInit. The local report
is from the development attempt before serial initialization; its build IDs and
stack are retained. The hosted report is from exact source 2f113864e36a57dc9043dcd8a1404e7da6225789,
[initial CI run](https://github.com/carabistouflette/goose-sqlite/actions/runs/41900281354).
Only checkout prefixes and hosted timestamp prefixes were normalized in these
logs; diagnostic content is retained. No failing cold-start attempt is counted
as a passing TSan run. They remain unresolved upstream diagnostics.

The maintained TSan scope serializes SQLite initialization but races the first
wrapper/key/registry use, then performs all teardown/WAL phases with both engine
and adapter instrumented. No suppression or engine source patch is used. See
[concurrency methodology](../../CONCURRENCY.md) for the exact scope and commands.

All checks use a shared host or hosted CI; neither exclusive core isolation nor
cross-platform performance follows from these correctness results.

## Native platform CI

The complete [source validation run](https://github.com/carabistouflette/goose-sqlite/actions/runs/41901233631)
passed on native Ubuntu 24.04 x86-64 and ARM64, plus a separate x86-64 TSan job.
[ci.json](ci.json) retains exact source/workflow/compiler-pin identity, job and
step conclusions, verified ARM architecture/width output and result excerpts.
Both native jobs run public runner/native/import tests, GCC/Clang sanitizer tests,
positive pinned-engine WAL tests, fuzzing and benchmark correctness smokes.
TSan runs the intentional-race control followed by scoped concurrency stress.
These native platform results do not provide ARM performance measurements.
