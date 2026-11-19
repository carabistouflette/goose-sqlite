# Validation

This page summarizes the test scope for runtime commit
[70ebfc263a1d1d8714899d5ec43510076668f5b5](https://github.com/carabistouflette/goose-sqlite/commit/70ebfc263a1d1d8714899d5ec43510076668f5b5),
the public main revision reviewed for this documentation. A passing test suite
does not prove the absence of bugs.

The historical exact-head [CI run 42084238303](https://github.com/carabistouflette/goose-sqlite/actions/runs/42084238303)
passed its then-existing three jobs: Linux x86-64, native Linux ARM64 and scoped
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

## Generated-path sanitizers

`make sanitize SANITIZER_CC=gcc` and `make sanitize SANITIZER_CC=clang` run
all seven public test programs through `scripts/sanitize.py`. File/checkpoint
programs receive isolated database paths. Exact completion markers and empty
stderr are required, rather than exit status alone. Tests are self-contained;
this is not a rerun of the long native recovery or engine matrices.

The compiler wrapper adds ASan/UBSan, `-O1 -g`, and `-UNDEBUG` after CMake's
Release flags. The sanitizer-only profile links **non-PIE** (`-no-pie`), retaining
the observed GCC16 libubsan/PIE linkage workaround; production builds are
unaffected. `--standalone` includes the Goose runtime in the compiled program.

| Layer | Coverage in this path |
| --- | --- |
| Generated Goose program and runtime | instrumented, seven public programs run |
| Native adapter | compiled through the sanitizer wrapper; native asserts enabled |
| Dynamically linked system SQLite | **not instrumented** |

The compiler path is a frozen copy addressed by wrapper content, resolved C
compiler path/hash and Goose binary hash. Flag or compiler-content changes use
a different path, avoiding stale native cache reuse from a mutable wrapper.
The pinned compiler's final cache identifier still uses a 32-bit path hash;
this is cache invalidation, not a cryptographic collision guarantee.

The gate deliberately separates two claims. First, the generated control object
must have undefined ASan **and** UBSan instrumentation references. Second, the
invalid FFI copy must trigger ASan at runtime. A plain generated object linked
with ASan reproduces the same interceptor error, but must be **rejected** by the
object gate. Runtime interception alone never qualifies generated-TU compilation.
This is not full path coverage or evidence of a SQLite API defect.

Every run reserves a fresh ignored evidence directory. Commands, exits, compiler
invocations, full stdout/stderr (including ASan reports), source/object hashes
and summaries remain there, with a CI artifact upload. Exceptions and timeouts
kill the owned command session and reap its leader. Each command is bounded at
300 seconds; no hard memory/disk isolation is claimed. The historical
`results/sanitize-2026-11-19.json` records the earlier gate and is not upgraded
retroactively. Its interceptor-only control claim is superseded by the compound
gate above; old CI duration descriptions are not current readiness evidence.

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
