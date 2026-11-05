# Cold SQLite initialization under ThreadSanitizer

## Finding

The reported startup conflict reproduces in pristine SQLite 3.54.1 without
Goose or the native adapter. On this host, eight workers released together from
a pthread barrier each call either `sqlite3_initialize()` or
`sqlite3_open_v2()` on their own private `:memory:` connection. In five fresh
processes per case, ThreadSanitizer reports a race in `sqlite3MutexInit` and
exits 66. The intentional-race control also reports the expected race and exits
66. The same test passes in all twenty cases after one `sqlite3_initialize()`
call on the main thread, before worker creation.

Both static and shared executables use the same instrumented SQLite object
(SHA256 `c2c771ce0f023d3a629692445db966c2af8624c23881fecbc81f52738c7084c8`).
The race appears in all five static and all five shared cold runs for both API
shapes; all corresponding preinitialized runs exit 0. This rules out the Goose
wrapper and the shared-library boundary as requirements for this reproduced
report. It does not prove that the access is harmless, establish application
data corruption, or prove the absence of another initialization race. Earlier
Clang 18/23 records point at other initialization publication accesses, so the
first reported location varies with the build and execution.

SQLite documents `sqlite3_initialize()` as thread-safe and recommends explicit
initialization before using other interfaces for portability. These diagnostics
do not resolve that discrepancy: a sanitizer report is retained as a report,
not relabeled as a false positive. The preinitialized control verifies the
different startup sequence only. No production initialization lock, success or
failure cache, engine patch, sanitizer suppression or instrumentation change was
introduced. Initialization failures remain retryable; this record does not
claim that concurrent cold initialization passes TSan.
See SQLite's [initializer contract](https://sqlite.org/c3ref/initialize.html)
and [threading modes](https://sqlite.org/threadsafe.html).

## Reproduction and provenance

The bounded recorder downloads SQLite's pinned 3.54.1 amalgamation and verifies
both the archive SHA256 and source SHA3 before building. It uses Clang 23.1.4,
`-O1 -g -fno-omit-frame-pointer -fsanitize=thread`,
`SQLITE_THREADSAFE=1`, and
`SQLITE_DEFAULT_WAL_SYNCHRONOUS=1`. Each case is a fresh process with eight
barrier-synchronized workers, at most twenty seconds per process, and no
TSan suppressions. Static and shared drivers link the same just-built SQLite
object. The positive race control must report a race before case results count.
Every exit, timeout, command, source/tool hash and output hash is in
[metadata.json](metadata.json); the 49 original compiler/control/case logs are
in [diagnostics.tar.gz](diagnostics.tar.gz), with member hashes in
[manifest.json](manifest.json). Checkout and build-directory prefixes are
normalized in log text; original raw output hashes are retained per command.

This run used the published base `f9abddb522b56c74f5346d41595a5d8835f9fbda`
plus the exact diagnostic script and driver source hashes recorded in
metadata.json. Those two files were uncommitted while running and had no
intervening edits; the later diagnostic commit retains those same bytes. It does
not contain production or wrapper code changes.

```sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD -u LD_AUDIT \
  python3 scripts/diagnose-cold-start.py \
  --cc clang --runs 5 --cpus 0,1,2,3 \
  --output .build/cold-start-diagnosis
```

For the earlier whole-wrapper test, positive control, broader thread/teardown/WAL
coverage, and existing serialized-initialization TSan scope, see
[concurrency validation](../../CONCURRENCY.md),
[the original diagnostics](../concurrency-recovery-2026-11-04/README.md), and
[the maintained startup/checkpoint results](../startup-checkpoints-2026-11-05/README.md).

**Status:** the engine-only race is reproducible and independently reviewed.
Its safety classification remains unresolved. The existing scoped TSan run
continues to initialize SQLite before worker creation; it is not a concurrent
cold-start TSan pass.
