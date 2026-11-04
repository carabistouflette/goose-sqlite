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
- Clang libFuzzer completed 1000000 cases with seed 219 and input size up to
  4096, followed by 100000 cases after the final comment-normalization change.
  The harness creates a fresh bounded in-memory database per input, fuzzes SQL,
  verifies arbitrary text/blob byte roundtrips, exact/undersized output copies
  and stale-token rejection. This does not exhaust SQL grammar, SQLite engine
  behavior or allocation-failure paths.
- Benchmark smoke passes all nine fixtures with correct checksums. A full
  three-pass recording retains 54 raw samples at 100000 ordinary iterations
  (scaled for large values) in [the evidence directory](../bench/results/validated-2026-11-04/README.md).
  Scope and reproducibility are in bench/README.md. No universal performance
  ranking follows from these measurements.
- A clean standalone clone built the pinned compiler from source with `make
  setup`, then passed `make check test` using that compiler. An independent
  reviewer also validated a separate standalone clone with the shared pinned
  compiler, both sanitizer builds, fuzz smoke and all benchmark fixtures.

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

Final independent security/correctness and quality/standalone reviews found no
remaining confirmed blockers in their scope. Their final minor finding concerned
SQLite accepting EOF block comments/leading empty statements while documentation
implied stricter syntax. The suffix scanner, contract and public regression cases
now consistently follow SQLite's first-statement grammar and prevent a second
executable statement. Review is evidence within its scope, not a certification.

## Publication compatibility review

A fresh publication review independently rechecked native sanitizers, public
payload/license/security boundaries and the retained benchmark fingerprints. At the initial publication snapshot, all
10 recorded source fingerprints matched the measured clean source and production
code. The follow-up changes and their separate evidence are described below. No confirmed publication blocker was reported in either review.

Cross-engine tests used isolated engine prefixes and package caches on the Linux
x86-64 host, not an Ubuntu VM. Exact versions, source IDs, compile options,
archive/package/library hashes and outcomes are retained in
[compatibility evidence](results/compatibility-2026-11-04.json):

- Upstream SQLite 3.37.0: public runner/native suites, GCC/Clang ASan/UBSan,
  external consumer runner/native imports and all nine benchmark-smoke fixtures.
- Upstream SQLite 3.45.1: public runner/native suites and GCC ASan/UBSan.
- Ubuntu noble-security SQLite 3.45.1-1ubuntu2.8 amd64 packages: public suites,
  GCC/Clang ASan/UBSan, 10000 fuzz cases, external consumer runner/native imports
  and all nine benchmark-smoke fixtures. Downloaded package SHA256 values were
  checked against Ubuntu package metadata.

The minimum/Ubuntu benchmark checks retain 54 smoke samples each and verify exact
build/runtime SQLite identity. Small iteration counts establish execution and
checksum correctness, not performance estimates. At that publication snapshot, production code and benchmark
sources were unchanged from the previously recorded evidence; publication added
platform documentation and a maintained isolated consumer test.

`make test` now also runs `scripts/test-import.py` against a local path from an
external temporary consumer and fresh package cache. To test a published Git pin,
use `python3 scripts/test-import.py --goose /path/to/goose --source
carabistouflette/goose-sqlite@<full-commit>`. Both runner and native executions must
produce the expected values after resource cleanup.

## Follow-up correctness and performance audit

A separate correctness review reproduced two misleading contract statements.
The interface documentation now explicitly distinguishes implicit RETURNING
writes that finalization can commit from still-open explicit transactions that
close rolls back. It also explains that wrapper validation involving SQLite
operations can replace a prior engine error message. Native regressions verify
both thread-exit transaction cases; no hidden cancellation/rollback behavior was
added to production code.

Profiling identified repeated zero initialization before full byte copies. The
Goose getter now preserves existing output length until its size check succeeds,
initializes only growth, and retains explicit clearing on all errors. All native
handle/state/type/size checks and copied ownership remain unchanged. Public tests
exercise changed contents at identical length, growth, shrinkage, empty bytes,
embedded NUL, both byte APIs and recovery after errors. A fresh review verified
these paths and matched the candidate's behavior to the measured variant.

[Matched profiling/timing evidence](../bench/results/reuse-2026-11-04/README.md)
retains seven alternating baseline/candidate passes and every fixture result.
A separate clean-source record covers all nine maintained Goose/C fixtures after
updating C output initialization for parity. Source/compiler/executable/native
archive hashes, captured compile flags and runtime identities are retained with
shared-host and measurement-scope limitations. Native instruction profiles did
not justify weakening checks or complicating the two-call interface.

Native test targets now include a separate process that installs test-only SQLite
allocator hooks before initialization. It tries 640 allocation-failure positions
across open, prepare, text binding and execution; checks returned errors/handles,
cleanup and SQLite's outstanding allocation count after every trial. GCC/Clang
ASan/UBSan suites pass. SQLite 3.37.0 and Ubuntu's 3.45.1-1ubuntu2.8 packages also
pass the expanded public suites, isolated consumer imports and Clang native/fault
checks. Counts of failing allocations differ by engine configuration. These hooks
are not compiled into the production adapter or used to change its global policy.

The fuzzer additionally checks a small model of up to 64 binding, clear, step,
reset, getter and finalize/reprepare operations per input, including invalid
states and stale tokens. SQL dictionary tokens improve grammar exploration.
A 100000-case run and then a 1000000-case seed-219 run passed after these
additions, as did a separate fresh 10000-case run by the reviewer. The longer
local run reused its warmed corpus; seed alone does not specify the corpus. These tests do not exhaust all allocation failures,
all SQL or all operation sequences; system SQLite remains a separate dependency.

## Reproduce

```sh
make setup
make check test
make test-native CC=gcc
make test-native CC=clang
make fuzz-native FUZZ_RUNS=1000000
make bench BENCH_ITERATIONS=100000
git diff --check
```

Build requirements and initial support scope are in README.md. GCC 16.2.1,
Clang 23, and system SQLite 3.54.1 were used on the initial host. CI targets Ubuntu
24.04 with its packaged SQLite; hosted CI success is separate from local results.
