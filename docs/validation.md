# Validation

This page summarizes the test scope for runtime commit
[70ebfc263a1d1d8714899d5ec43510076668f5b5](https://github.com/carabistouflette/goose-sqlite/commit/70ebfc263a1d1d8714899d5ec43510076668f5b5),
the public main revision reviewed for this documentation. A passing test suite
does not prove the absence of bugs.

The exact-head [CI run 42084238303](https://github.com/carabistouflette/goose-sqlite/actions/runs/42084238303)
passed all three jobs: Linux x86-64, native Linux ARM64 and scoped
ThreadSanitizer. The workflows use the compiler pinned in
[GOOSE_REVISION](../GOOSE_REVISION).

## Correctness checks

- make check test checks and runs the Goose API tests and examples, native import
  tests and file tests.
- make test-native CC=gcc and make test-native CC=clang run native adapter,
  ASan/UBSan, thread and storage-recovery tests.
- make fuzz-native runs the native SQL/API fuzzer. The pinned-engine workflow
  separately checks WAL behavior with an engine that has the required WAL-reset
  fix.
- CI runs the public tests on x86-64 and ARM64. See
  [recovery tests](../tests/RECOVERY.md) and
  [concurrency tests](../tests/CONCURRENCY.md) for the detailed test contracts.

## ThreadSanitizer limitation

The maintained TSan test initializes SQLite on one thread before starting its
workers. It checks concurrent first use of the adapter registry and later
thread teardown/WAL paths. It is not a concurrent cold-engine initialization
test.

Separate tests on unmodified SQLite 3.54.1 reproduce TSan reports during cold
engine initialization with both static and shared linking. Matched tests pass
when SQLite is initialized before workers start. The diagnosis does not establish
whether the report is a C-level race or a sanitizer-modeling issue. No production
workaround or clean cold-start claim follows. See the
[cold-start results](../tests/results/cold-start-2026-11-05/README.md).

## Performance records

Performance is measured separately from CI correctness. Each result is tied to
its source, compiler, engine, workload and raw samples. See the
[benchmark currentness table](../bench/CURRENTNESS.md) before using a result as
a claim about the current runtime. Shared-host measurements are not CI thresholds
or universal performance rankings.
