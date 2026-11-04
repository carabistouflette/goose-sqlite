# Storage recovery validation

15214 trials, 14968 injected fault/crash points, 24 crashes after acknowledged
success. All complete rows/BLOBs and integrity checks pass; backup sources remain
unchanged. Every observed injected-error outcome is the old generation. Process
crashes before acknowledgement may leave a complete old or new generation.

| Configuration | Trials | Fault/crash points | Explicit unsupported WAL groups |
|---|---:|---:|---:|
| Host SQLite3.54.1 / GCC adapter ASan/UBSan | 3456 | 3408 | 0 |
| Host SQLite3.54.1 / Clang adapter ASan/UBSan | 3456 | 3408 | 0 |
| Pinned SQLite3.54.1 / Clang engine+adapter ASan/UBSan, WAL required | 3456 | 3408 | 0 |
| SQLite3.37.0 / Clang adapter ASan/UBSan | 2423 | 2372 | 27 |
| Ubuntu3.45.1-1ubuntu2.8 / Clang adapter ASan/UBSan | 2423 | 2372 | 27 |

[summary.json](summary.json) retains source hashes checked against the exact
recorded Git commits, binary/engine hashes, SQLite source identities, build flags,
compiler identities and event counts. Compiler versions/hashes were collected
after completion from unchanged build configurations; the driver captured the
source/binary/engine hashes. These are not timing measurements.

The five runs produce two distinct logical record streams. records-1.jsonl and
records-2.jsonl retain every trial, with canonical key/whitespace formatting;
identical streams are deduplicated and referenced by SHA-256 in the summary.
No failed trial was discarded to obtain the reported results. Earlier development
runs preceded stricter review-driven oracle changes; the retained records use the
final native harness. Later driver changes enforce required WAL skips and make
optional build-flag metadata portable to other CMake generators; stored source
hashes identify exactly which version produced each run.

Reproduce with make test-native CC=gcc / CC=clang and
python3 scripts/test-wal-engine.py. The pinned script requires positive WAL
coverage. [Methodology](../../RECOVERY.md) describes private fixtures, error and
crash markers, fresh-connection verification, recovery transactions and bounds.
CI runs these suites alongside the public runner/native/import tests.

The model preserves the OS cache. It does not model power failure, torn or
reordered writes, real disk exhaustion, truncate/delete/SHM errors or every SQLite
configuration. A finite successful campaign does not prove the absence of bugs.
No production defect was confirmed; production APIs and policies remain reviewed
and checked. SQLite engine updates and appropriate filesystem handling are still
application responsibilities.
