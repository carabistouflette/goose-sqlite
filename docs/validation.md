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

## Alternative feature and performance comparison

[Primary-source research](alternatives.md) includes two other Goose bindings,
Python sqlite3, rusqlite and SQLiteCpp. The follow-up implements checked named
parameter lookup/count, copied column names, 64-bit direct change counts, signed
insert IDs and actual autocommit status. Regression cases cover sparse/repeated
names, copied empty/duplicate/long aliases, all live metadata states, stale and
foreign-thread handles, unaligned outputs, negative/rolled-back IDs, triggers,
WITHOUT ROWID tables and engine-driven transaction rollback. Remaining advanced
feature gaps are explicit; this is practical parity in a bounded subset.

The [alternative experiment](../bench/results/alternatives-2026-11-04/README.md)
retains245 samples before and245 after the reusable checked-fetch improvement,
with seven shuffled passes and seven fixtures per five implementations. The
loaded SQLite object hash matches in all five; runtime identity/options are
explicit for four callers and inferred from the same object for Goose. Requested
Rust lto=false metadata was overridden by user configuration: an explicit erratum
records actual Thin LTO/codegen/incremental settings without rewriting raw data.
The maintained harness now enforces that observed profile. Python caching,
Unicode conversion, Rust UTF-8 validation, owned allocations and Goose's security
policy are differences in the measured API paths, not equivalent-policy claims.

The private fetch helper removes a redundant FFI round trip when existing output
length fits the next value. First/growing outputs retry with a bounded required
length. It retains all byte_column validations and copied ownership; public
failures still clear output, including oversized preseed arrays. Legacy native
size/copy functions remain compatible. Native tests now force allocation failure
during stored UTF-16 TEXT-to-UTF-8 conversion, checking SQLITE_NOMEM, untouched
native buffers and resource recovery; total fault-position trials are656.
GCC/Clang sanitizers, public runner/native/consumer tests and 100000 updated
state-model fuzz cases pass. SQLite 3.37.0 also passes the expanded public and
Clang native/fault suites. CI additionally executes all five alternative smoke
runners with the system Python to preserve the shared-engine requirement.

Two design reviews, a metadata implementation review, a checked-fetch review,
benchmark review and fresh final safety/comparison audits informed this work.
Actionable timing-boundary, Python optimization-environment and Rust profile
provenance findings were corrected. No remaining confirmed native correctness
or safety blocker was reported within those reviews' scope.

## WAL, backup and incremental BLOB follow-up

Production code is at d030ad327b833b76dcf8969b25b4f3b1d443708a; test/compatibility
follow-ups are through b01179509d63a7e5e73b0de11de03dad4e2a81d2. New public tests
run under the Goose runner and compiled executables; the isolated standalone
consumer also exercises writable/read-only BLOBs and online backup.

The current host passes make check/test, GCC and Clang ASan/UBSan native suites,
and an updated 100000-case seed-219 fuzz campaign including a model of BLOB range
writes/reads, stale token replacement, zero-length operations and rollback expiry.
That campaign reused the warmed local corpus; seed alone does not identify it.
Fault tests now cover 912 allocation positions (128 BLOB-open and 128 backup
positions added). Test-only lookaside is disabled before SQLite initialization
so allocations reach the injected allocator; production configuration is unchanged.
All connections close and engine memory accounting returns to baseline per trial.

Public runner/native/consumer and GCC/Clang sanitizer suites also pass against
upstream SQLite 3.37.0 and Ubuntu 3.45.1-1ubuntu2.8. A generated-column restriction
assumption was corrected after the minimum engine permitted an ordinary column
in such a table; newer engine versions reject the table. Old/unrecognized engines
reject requested or detected WAL, including unknown distributor backports; their
rollback-journal tests continue to pass.

The maintained scripts/test-wal-engine.py verifies the pinned 3.54.1 archive
SHA-256 and its sqlite3.c SHA3-256 against the upstream release record, then builds
**both engine and adapter with ASan/UBSan**, using DEFAULT_WAL_SYNCHRONOUS=1.
Local native/912-position fault/storage suites pass under that instrumented engine.
The test-only auto-extension captures a connection for post-open policy inspection:
caller PRAGMA denial is checked first, then the test removes its authorizer only
to verify synchronous=FULL after an OFF default and preserved EXTRA after EXTRA.
There is no production pointer or authorizer bypass API. Backup tests verify
READONLY on 8192-to-4096 page-size mismatches with existing in-memory/WAL targets,
retaining their original row42. [Pinned-engine evidence](../bench/results/storage-2026-11-04/wal-engine-validation.json)
records source, compiler, flags and hashes. CI runs this path separately from the
packaged-engine suites and adds all four storage benchmark smoke paths.

Two initial implementation reviewers, fresh final native/contract and benchmark
reviewers, and a publication/provenance review inform this slice. The initial
pointer-type build issue, old-engine test assumption and minor metadata/reporting
findings were fixed. No confirmed production correctness or memory-safety blocker
remained within the completed reviews' scope. Tests are evidence, not a proof
against every possible bug or a security endorsement of old SQLite versions.

[Storage results](../bench/results/storage-2026-11-04/README.md) retain two complete
144-sample series. The original overlaps CONFIG timing on CPU7 and is unmodified;
the separate repeat follows explicit release. All requested bytes/checksums match,
loaded engines match, full-value regressions and sample spreads are reported.
Both methods benefit from range access; no engine, disk, allocator or universal
wrapper-performance claim follows.

## Storage I/O and process-crash recovery

The [test-only recovery harness](../tests/RECOVERY.md) covers prepared UPDATE
transactions, explicit incremental BLOB writes and bounded online backup under
rollback journal and recognized patched WAL engines. It enumerates write/sync
cutpoints through a terminal no-hit success, including one-shot/persistent errors
and actual process termination before callbacks or immediately after successful
commit/backup acknowledgement. Strict storage types and all bytes are checked.

The completed matrix contains 15214 trials and 14968 injected fault/crash points:
GCC and Clang each pass 3456 trials on host SQLite 3.54.1, the fully instrumented
pinned engine passes 3456 with WAL required, and SQLite 3.37.0 / Ubuntu 3.45.1 each
pass 2423 with 27 explicit unsupported-WAL group skips. All 24 acknowledged-crash
controls recover the complete new generation. Observed injected-error outcomes
recover the complete old generation; the general error oracle allows a complete
old or new generation, since an I/O error is not a commit receipt. Backup sources
remain unchanged; fresh checked transactions succeed after recovery verification.

[Records and provenance](../tests/results/recovery-2026-11-04/README.md) include
all cutpoints, counts, source/binary/engine hashes and compiler details. Identical
record streams across compiler/engine runs are stored once with hash references.
Three independent design/implementation/final reviews informed the harness.
Sanitizer-diagnostic handling, explicit acknowledged crash controls, strict integer
oracles, verification-before-write ordering and mandatory pinned WAL coverage
were strengthened during review. No production defect was confirmed by this
campaign. Runtime code and its safety checks required no change.

The failure model covers complete-call xWrite/xSync errors and process crashes.
It excludes torn writes, reordered writes, real full disks, truncate/delete/SHM
failures and power-loss durability. Host tests instrument the adapter; the pinned
engine run instruments both engine and adapter. These are correctness checks,
not performance measurements or proof against every storage failure.

## Statement diagnostics, recovery examples and registry lookup

New public diagnostics tests cover allowed metrics, Ready/Row/Done/Failed states,
reset-returning-old-value semantics, the MEMUSED reset exception, unknown metrics,
default/wrong-kind/stale handles and deterministic zero failure outputs. Native
cases cover unaligned outputs, invalid reset flags and foreign-thread tokens.
The runnable transaction example tests original/recovery error separation, failed
BEGIN ownership, nested savepoints and INSERT OR ROLLBACK ending the outer scope.
Host, minimum 3.37 and Ubuntu 3.45 runner/native/consumer/example suites pass using
isolated public executable directories. Overlapping exploratory output paths were
caught, excluded from validation and replaced with those isolated reruns.

A Callgrind native scan profile identified repeated pthread registry calls. The
small C11 TLS cache retains pthread-key ownership, all thread/token/generation
validation and copied values. Publication follows successful key association;
destructor entry clears the cache before SQLite callbacks can create fresh state.
A trusted native userdata cleanup regression rejects old tokens during teardown,
uses/closes a fresh registry, and verifies main-thread isolation. It passes on
both original and optimized implementations. GCC/Clang ASan/UBSan and the pinned
instrumented engine pass; minimum/Ubuntu native Clang checks also pass with the
new diagnostics and teardown regression. The updated 100000-case seed 219 fuzz
campaign passes after the cache change, using the warmed local corpus.

[Workload evidence](../bench/results/workloads-2026-11-04/README.md) retains 350
baseline, 140 paired and 350 final samples, common engine/profile checks, a launcher
RSS probe and redacted instruction profile. Sources were clean/frozen and checked
before/after measurement. Actual SQLiteCpp Release/external-engine flags are
verified after fresh configuration; an exploratory cache-reset O0 build and an
ambient Rust compiler-cache build failure were fixed before principal timings.
Design/API/benchmark/registry implementation and final data reviews informed this
follow-up. Mixed/slower results remain visible. Native-executable performance
claims do not imply the dynamic runner has identical TLS code generation.

## Concurrent connections, expanded I/O and ARM64

The follow-up uses final test source at 4a7e36368f25a00bb9a0ab722043aa2d2a642c67.
[Retained results](../tests/results/concurrency-recovery-2026-11-04/README.md) include
source/binary/engine/compiler hashes, all recovery cutpoints, concurrency counters,
the intentional TSan positive control, and original cold-start TSan diagnostics.

GCC/Clang host and fully instrumented pinned-engine ASan/UBSan recovery each passed
4410 trials; minimum SQLite 3.37 passed 2915 trials with 57 explicit unsupported-WAL
group skips. Total 16145 trials include 15710 fault/crash points and 21 crashes after
acknowledged success. Added read/truncate/delete/SHM-map/SHM-lock kinds all have
actual one-shot and persistent hits on modern engines. Complete old/new state,
all data and padding bytes, source immutability and fresh integrity checks passed.
Truncation errors can legitimately recover the complete new generation.

Concurrent tests passed on host GCC/Clang, the pinned ASan/UBSan and TSan engines,
and the minimum engine (explicit WAL skip). Each verifies 3072 unique tokens and 64
reentrant thread-exit rollback callbacks. Positive WAL runs also require 256 final
rows and at least 160 validated reader snapshots. TSan first detects an intentional
race, then requires a diagnostic-free stress run after serial engine initialization.
Concurrent SQLite cold start is outside that TSan result: initial local/hosted
attempts produced unresolved engine diagnostics. ASan/UBSan retains cold starts;
no engine patch or sanitizer suppression is used. See [methodology](../tests/CONCURRENCY.md).

Native Ubuntu 24.04 x86-64 and ARM64 jobs, plus the separate x86-64 TSan job,
passed [the complete source validation](https://github.com/carabistouflette/goose-sqlite/actions/runs/41901233631).
Both architectures execute the pinned Goose compiler and runner/native/import
suites, GCC/Clang sanitizer tests, verified pinned-engine positive WAL, fuzzing and
benchmark correctness smoke checks. Architecture and 64-bit width are checked on
ARM64. These smoke checks do not provide ARM performance measurements or rankings.
The local public/import suites and 10000-input fuzz smoke also passed.

## Explicit startup and manual WAL checkpoints

Implementation/test source cb0566c4c0ddf483ce4546a339d6fac4ab88742c passed the
[complete native x86-64/ARM64 and scoped TSan matrix](https://github.com/carabistouflette/goose-sqlite/actions/runs/41929243279).
[Current records](../tests/results/startup-checkpoints-2026-11-05/README.md) retain
all source/binary/compiler/engine identities, actual flags, raw recovery cutpoints,
concurrency/checkpoint counters, fresh-seed fuzz evidence and hosted CI conclusions.

`initialize()` directly exposes retryable engine startup without a wrapper lock,
cached failure or shutdown API. Two injected initialization failure positions
recover successfully before shutdown, then prove a working connection. Repeated
initialization preserves live statements/ROW reads. TSan uses this production entry
before racing registry/key use. The original engine cold-start reports remain
unresolved; this is explicit sequencing, not a claim of passing cold-start TSan.

`checkpoint` adds four explicit main-schema modes, idle/writable/thread checks,
unaligned-safe sentinel outputs and valid partial progress on BUSY. Default file
opens discover existing WAL; exact private memory needs no discovery on recognized
engines. Tests cover a competing checkpoint's immediate BUSY/unavailable counts,
reader snapshots, writer contention, idle bindings, rejection of active main
transactions, readonly/stale/foreign tokens and successful truncation. They run
under both ordinary sanitizers and the fully instrumented TSan engine.

Four final recovery configurations passed 16968 trials and 16460 fault/crash
points, including 24 acknowledged crashes. Modern engines each add 268 checkpoint
trials/250 fault-crash points; every outcome preserves the previously committed
new generation, with fresh full-byte/integrity checks and successful checkpoint
retry before any write. The minimum engine reports 76 unsupported WAL groups.
A fresh tracked-corpus 100000-input fuzz run, public runner/native/isolated imports
and native/fault/storage suites also pass on the final tested source; minimum
engine public/native compatibility remains checked. Checkpoint I/O has no hard
page/time/memory budget, and process death is not power-loss simulation.

The [row-cache experiment](../bench/results/row-cache-2026-11-04/README.md) retained
all 180 samples from nine pairs across ten fixtures and was rejected after mixed
results and wide shared-host spreads. In that startup/checkpoint slice, production
getters/step remained unchanged;
automatic-schema-reprepare regressions remain tested. No statistically established
regression or general performance improvement is claimed. Existing cross-language
benchmarks retain their original versions/source scope.

## Reproduce

```sh
make setup
make check test
make test-native CC=gcc
make test-native CC=clang
python3 scripts/test-wal-engine.py
make fuzz-native FUZZ_RUNS=1000000
make bench BENCH_ITERATIONS=100000
git diff --check
```

Build requirements and initial support scope are in README.md. GCC 16.2.1,
Clang 23, and system SQLite 3.54.1 were used on the initial host. CI targets Ubuntu
24.04 with its packaged SQLite; hosted CI success is separate from local results.

## Zero-filled binding and BLOB allocation errors

Implementation/test source ead19309bef4394ffc041f079d50e2a8d78b7388 passed
[all three native x86-64/ARM64 and scoped TSan jobs](https://github.com/carabistouflette/goose-sqlite/actions/runs/41939789987).
[Retained correctness evidence](../tests/results/zeroblob-2026-11-05/README.md)
covers host GCC/Clang, fully instrumented pinned engine, minimum SQLite 3.37,
public runner/native/import suites and a fresh 100000-input fuzz campaign.

The getter regression forces deferred positive-length BLOB allocation to fail;
the old implementation returned successful empty output. The fix reads typed
BLOB length before materialization and avoids pointer expansion for empty BLOBs.
Tests distinguish OOM from legitimate empties even after another statement fails.
TEXT conversion order remains unchanged. New zero bindings cover signed bounds,
lifecycle, stale/foreign handles, reset/clear, sparse indices and transactional
incremental writes. Security/resource limits and the unresolved cold-engine TSan
diagnostics remain as documented.

[The performance record](../bench/results/zeroblob-2026-11-05/README.md) retains
270 samples and 30 allocator probes. It includes existing SQL zero creation;
timing is mixed and binding-phase allocation is not total memory usage.

## File-backed benchmark correctness

Measured source 52dca0d4f3d5718b5f7c4c586249d7404c80f783 passed complete five-caller
DELETE/WAL smokes with independent full-data and integrity checks before the
principal run. The principal series completed all 270 process samples, 34560
operation latencies and 30 separate warmups. Bad policy/count/negative-code and
corrupt-payload fixtures were separately rejected. [Results and provenance](../bench/results/filebacked-2026-11-05/README.md)
retain outcome counts, same-connection BUSY recovery, shared engine and policy
proof, Git/source/compiler identities, filesystem observations and raw samples.

The test-only native policy probe checks denied PRAGMAs before inspecting two
connections in its isolated process; it is not linked into the production library.
Hosted benchmark smoke explicitly selects DELETE on older packaged engines;
full positive WAL remains covered by the existing pinned-engine native tests.
No production implementation, native manifest or compiler pin changed. Original
cold-engine TSan diagnostics and serialized engine-init scope remain unchanged.

## Coordinated WAL reader/writer validation

Clean 8133274 passed independent actor/controller reviews and exact-source
[CI 42029462705](https://github.com/carabistouflette/goose-sqlite/actions/runs/42029462705):
x86-64, native ARM64 and existing scoped TSan jobs. The new positive-WAL mixed
smoke uses a checksum-verified normal test-only engine on both architectures; it
is correctness evidence, not ARM performance evidence. Test-only policy inference
checks denial before fixed inspection and adds no public authorizer escape.

The [principal record](../bench/results/mixedwal-2026-11-05/README.md) passed 50 pairs
and five deterministic qualifications: held snapshots survive commit, fresh reads
see published epochs, uncommitted updates stay invisible, rollback and independent
full final-data/integrity checks pass. All 6,400 commits and 69,359 snapshots were
checked; every pair passed all four intermediate progress bands and clean exits.
An independent data audit recomputed all 20 orientation/role summary rows and
checked raw stdout/events, counts, quantiles, gates, artifact/source/build/engine
hashes, rates and separate lifetime RSS. No principal failure or automatic rerun
occurred. An earlier source-changed development smoke remains explicitly incomplete
and archived outside principal results.

Broken-pipe stream cleanup, owned-group timeout handling, malformed protocol and
all-BUSY commit-floor behavior were separately checked. Shared-host/incidental
build and coupled same-filesystem logging costs remain disclosed. Runtime/native/
manifest/CMake/compiler-pin bytes remain unchanged from 8a1d0d7. The unresolved
cold-engine TSan and serialized-engine-initialization scope remain unchanged.

A final finite fault probe found that a broken actor's full stdin pipe could block
the recorder command flush outside its deadline checks. Actor command pipes are
now nonblocking; a real filled-pipe probe verified immediate backpressure failure,
owned-child termination and closure of every stream. This recorder-only correction
postdates the principal source and changes no production code or retained timing.
