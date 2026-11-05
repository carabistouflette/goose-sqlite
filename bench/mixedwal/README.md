# Coordinated finite WAL reader/writer pairs

```sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD -u LD_AUDIT /usr/bin/python3 \
  bench/mixedwal/measure.py --goose /path/to/pinned/goose \
  --attempts 128 --rows 32 --read-cap 20000 --rounds 10 \
  --writer-cpu 6 --reader-cpu 7 --coordinator-cpu 5 \
  --output .build/mixedwal-principal
```

Choose allowed, coordinated CPUs. Reader and writer run on distinct CPUs; their
orientation swaps on odd rounds. The coordinator uses a third CPU where one is
available. Affinity is not exclusive isolation. Ten rounds give five of each
orientation per caller; caller order shuffles per round with seed 219. Output
must be new and under ignored `.build` or outside the source checkout. Principal
recording requires clean source and checks its bytes against Git blobs.
Use `--smoke --attempts 8 --rows 4 --rounds 2` for correctness checks. Smoke skips
intermediate-progress coverage only, not operation or successful-commit checks.

Requires Linux, Python 3.11+, GNU time/findmnt/taskset, GCC/G++, CMake, Rust/Cargo,
the pinned Goose compiler and the clean pinned SQLiteCpp cache used by the
[alternative harness](../alternatives/README.md). The shared engine must support
the binding's recognized patched WAL gate. No public library, authorizer, token,
ownership or work-limit policy is weakened.

## Data and deterministic qualification

Each implementation runs one reader process and one writer process, each opening
its own connection once. Callers are Goose, raw C API in a C++ driver, SQLiteCpp,
rusqlite and isolated Python. Engine/profile/dependency pins and policy differences
follow the [file-backed methodology](../filebacked/README.md).

The fixed table has IDs 0..ROWS-1, one integer epoch and a 128-byte binary payload
per row. Payloads encode epoch and ID in every middle byte, with NUL/0xff endpoints.
All valid payloads are precomputed before READY; a bounded product caps allocation.
Reader scans check storage types, IDs, a common epoch and all owned payload bytes,
then consume DONE/reset. Each writer UPDATE must change one row. Priming precedes
READY and preserves logical epoch 0.

A separate qualification file is mandatory for each caller:

1. Reader establishes an actual epoch-0 table snapshot and holds its transaction.
2. Writer commits all rows at epoch 1; held reader must still see epoch 0.
3. Reader ends that transaction and sees epoch 1 in a fresh transaction.
4. Writer holds an uncommitted epoch-2 update; a fresh reader still sees epoch 1.
5. Writer rolls back; fresh reader and independent reopened oracle see epoch 1.

Parent uses flushed, bounded line protocol over stdin/stdout, not a SQLite hook
or native IPC extension. Selectors drain both stdout/stderr pipes. Every received
line and command is journaled with parent monotonic/UTC timestamps. A pair has a
120-second deadline. Malformed output, unexpected EOF, missing END, nonzero exit,
operation caps and unexpected SQLite errors fail the pair. Its database, raw logs
and incomplete metadata remain. Timeout cleanup targets only the two owned process
groups. Protocol details and fixed gates are in [CONTRACT.md](CONTRACT.md).

## Mixed work and gates

After both READY responses parent sends G to both roles. Writer makes a fixed
number of BEGIN IMMEDIATE attempts. Success updates every row to successful
commits+1 and commits. Only BEGIN-BUSY is accepted as a nonzero result; it must
preserve autocommit and the published epoch. UPDATE/COMMIT errors invalidate the
pair with actual stage/code diagnostics. There are no application retry loops.

Reader performs one checked transaction, emits latency/code/epoch, then waits for
N or S outside its operation clock. Parent issues one reader command at a time;
after observing writer DONE it sends S following the next R. Reader work count
is consequently variable. Cap/deadline exhaustion is a failure, not truncation.
Successful observed epochs must be nondecreasing and in seed 0..final commits.

A principal pair needs at least max(8,ceil(.75*ATTEMPTS)) writer commits and reader
observations in all four intermediate progress bands defined in CONTRACT. The
commit floor also applies in smoke; only the intermediate-band gate is relaxed.
This proves useful interleaving, not continuous overlap. Failing pairs are retained
and never automatically rerun.

An initialized idle parent WAL anchor remains open until both workers exit, with
no pending cursor/transaction. This keeps last-close work outside child role clocks.
Independent read-only verification checks all final IDs/epochs/payloads, WAL mode
and integrity before anchor cleanup. Pre/post WAL and DB hashes are recorded;
successful files are removed only afterward. Final epoch equals writer commits.
Threshold 1000 and file observations are retained, but peak WAL size and causal
checkpoint-tail attribution are not measured. No power-loss or cold-cache proof.

## Timing and interpretation

Operation clocks include SQL, result/change/autocommit checks, and reader
copying/full-byte verification. Event formatting/flushing follows these clocks.
Recorded writer-loop commits/s includes event logging/bookkeeping. COORDINATED
reader snapshots/s additionally includes per-snapshot parent waits. Parent pair
wall and command/event times remain separate. `stop_dispatch_lag_ns` is parent
STOP-send minus writer-DONE-receive; `reader_done_lag_ns` is reader-DONE-receive
minus writer-DONE-receive. Neither subtracts independent language clock epochs.

Successful-operation and BEGIN-BUSY latencies have separate nearest-rank p50/p95/
p99, extrema and counts. Empty distributions remain null. BUSY is not required
with one WAL writer. Preserve all vectors and do not pool percentiles or hide
low-count tails. These are coupled implementation pairs, not identical offered
reader load, isolated writer overhead, free-running saturation, fairness, retry
quality or exact continuous overlap.

Each role's GNU time peak RSS includes startup, payload precomputation, setup,
verification, waits and cleanup. Role peaks are not contemporaneous and must not
be summed as simultaneous memory. Shared-host load, governor, topology and warm
filesystem scope remain recorded; no universal library ranking. Existing unresolved
cold-engine TSan limitations remain unchanged.

## Provenance and optional selected engine

Relevant sources, native/header/build scripts, shared C++ helpers and every Rust/
Python/Goose worker are frozen. Working/frozen bytes, HEAD/dirty state, tools,
generated source, archives, executables, dependencies and loaded engines are
rechecked before completion. Parent seeding/verifier and native probe must use
the same mapped SQLite object as every worker. Actual Goose must match its pin.
Raw event journals and role stdout/stderr flush as they arrive; successful
structured pairs flush to samples.jsonl. No previous output is overwritten.

Default recording rejects loader overrides. `--engine-dir DIR` permits only an
exactly matching resolved LD_LIBRARY_PATH, with LD_PRELOAD/LD_AUDIT empty; that
path is deliberately restored after cleaning child environments. If evidence.json
is present in DIR, its content/hash are retained and engine_sha256 must match the
common loaded object. CI bootstraps a checksum-verified normal (non-ASan) pinned
engine to exercise positive WAL on older packaged systems. Those smoke records
are correctness evidence, not performance measurements.

Parent event/stdout journals are flushed on the same recorded filesystem as the
SQLite fixtures. Logging and coordinator load are part of this coupled workload.
Reader counts and cadence vary by implementation; they are not identical offered
load or isolated writer-API work. Expected payload tables are precomputed before
READY but remain included in each role's whole-lifetime RSS.

Available package/core/thread sysfs topology fields are recorded for every
selected CPU; unavailable hybrid-core identity remains unknown. Cleanup closes
all streams even after broken-pipe errors, preserving the original failure. The
CI bootstrap uses owned-group build timeouts and replaces itself with the bounded
orchestrator rather than timing out a wrapper while leaving actors behind.
