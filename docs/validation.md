# Validation record

Initial validation on 2026-11-04, Linux x86-64. This is a record of completed
checks, not a security certification or a guarantee on other platforms.

## Completed checks

- Public interface format/type checks and behavioral suites pass using the exact
  Goose compiler in GOOSE_REVISION. Both the in-process runner and native
  executables pass. The example prints `1: Goose`.
- Public cases cover copied bindings/outputs, embedded NUL, empty text/blob/NULL,
  strict storage types, SQLite extended errors, stale aliases after slot reuse,
  explicit reset states, policy denial, foreign keys, explicit rollback, work
  interruption/recovery, exact SQL/value bounds, persisted data, read-only writes,
  real two-connection contention, RETURNING, failed-open recovery and cleanup
  errors. File suites use a private temporary directory for each mode.
- Production C adapter passes GCC and Clang ASan/UBSan tests. Cases include
  byte-aligned outputs, exact/undersized copy buffers, foreign-thread token
  rejection, independent thread connections, registry exhaustion/recovery,
  automatic thread-exit cleanup releasing an exclusive file lock, and errors
  returned by reset/finalize. System SQLite is dynamically linked and is not
  instrumented by this adapter sanitizer build.
- Clang libFuzzer completed 100000 cases with seed 219 and input size up to 4096.
  The harness creates a fresh bounded in-memory database per input, fuzzes SQL,
  verifies arbitrary text/blob byte roundtrips, exact/undersized output copies
  and stale-token rejection. This does not exhaust SQL grammar, SQLite engine
  behavior or allocation-failure paths.
- Benchmark smoke passes all nine fixtures with correct checksums. Measurement
  scope and reproducibility are in bench/README.md. No universal performance
  ranking follows from these measurements.

## Independent review

Two reviewers challenged the initial design and first implementation for
correctness/security and interface quality. Findings resolved before the feature
commit: thread-exit cleanup, explicit step/reset state, no-wrap tokens, strict
storage types, immutable connection policies, URI rejection, truthful work-limit
scope, and unsupported virtual-table policy. The public execute helper now
rejects result-bearing statements before stepping, preventing rejected RETURNING
operations from writing. Policy tests require exact authorization denial.

A separate performance reviewer found different native optimization flags in
the original baseline. The corrected harness links both callers to the same
Goose-built static adapter and same SQLite shared library, captures actual native
flags/artifact hashes/runtime identity, and checks both insert count and values.
The implementation retains its straightforward byte-copy interface; there is no
measured justification for removing validation or adding a more complex path.

## Reproduce

```sh
make setup
make check test
make test-native CC=gcc
make test-native CC=clang
make fuzz-native FUZZ_RUNS=100000
make bench BENCH_ITERATIONS=10000
git diff --check
```

Build requirements and initial support scope are in README.md. GCC 16.2.1,
Clang 23, and system SQLite 3.54.1 were used on the initial host. CI targets Ubuntu
24.04 with its packaged SQLite; hosted CI success is separate from local results.
