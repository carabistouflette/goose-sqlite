# File-backed transactions and controlled contention

```sh
env -u LD_LIBRARY_PATH -u LD_PRELOAD -u LD_AUDIT /usr/bin/python3 \
  bench/filebacked/measure.py --goose /path/to/pinned/goose \
  --transactions 128 --batch 16 --runs 9 --cpu 6 \
  --output .build/filebacked-principal
# Development correctness smoke, dirty source explicitly labeled:
env -u LD_LIBRARY_PATH -u LD_PRELOAD -u LD_AUDIT /usr/bin/python3 \
  bench/filebacked/measure.py --goose /path/to/pinned/goose \
  --transactions 2 --batch 2 --runs 1 --smoke --journals delete \
  --output .build/filebacked-smoke
```

Select an allowed/coordinated core or omit affinity; no exclusive isolation.
Requires Linux, GNU time/findmnt, GCC/G++, CMake, Cargo/Rust, Python 3.11+ with sqlite3,
normal Goose requirements and clean pinned SQLiteCpp cache
`.build/alternatives/SQLiteCpp` (provisioned by the alternative benchmark).
Output must be new, outside the checkout or under ignored `.build`.
Principal recording requires clean committed source. `--journals both` is the
default; delete/wal select explicit subsets recorded in metadata. Unsupported
WAL fails closed; no silent skip or fallback. Packaged older-engine CI uses the
DELETE-only smoke. Full principal comparisons require recognized patched engines.

Five callers: Goose, raw SQLite C API in a C++ driver, SQLiteCpp 3.4.0 at
`df0a28ca9733f687ab7ce77f070c0df84368a45e`, rusqlite 0.41.1 and installed Python.
All callers/probe must load the same SQLite object hash. Runtime identity/options
are queried from that object and inferred for callers by exact loaded-object
match. Python runs with -I and optimize0 so checks remain enabled.

## Workloads

DELETE/WAL each cross commit, rollback and BUSY rejection. Every child gets a
fresh 4096-byte-page rowid/BLOB file with one guard row and 128-byte payloads
containing NUL/0xff. Seeding commits, truncates seed WAL and closes; initial WAL
is absent/empty. Files are warm in OS cache, not cold-cache measurements.

Commit/rollback run N BEGIN IMMEDIATE transactions with BATCH reused INSERTs,
each checking direct changes1 and completion/reset, then COMMIT/ROLLBACK.
Rollback's persisted guard-only result cannot alone prove inserts happened;
changes1 is mandatory. Before timing, every caller primes an inserted row with
rollback and empty commit/rollback controls on the measured connection.

BUSY uses a second connection with a held write transaction and modified guard.
Every timed primary BEGIN must return primary BUSY and retain autocommit; no
retries or racing release. After timing, blocker rollback restores the guard and
the SAME primary must begin/insert/commit. This measures controlled rejection,
not concurrent-writer throughput, fairness, queueing, timeout waiting or retry
latency. Both connections' policies are verified.

Control SQL remains each caller's ordinary API path: Python may cache SQL while
Goose prepares/finalizes execute; C/C++ controls/status use raw C, selected row
operations use the matching statement API. SQLiteCpp RAII destructors expose no
finalization status. Python exposes no NOMUTEX/private-cache flags. Other
security/work-limit/allocator policies differ. This is not identical API overhead.

Every transaction/attempt retains monotonic nanoseconds and actual SQLite code.
The enclosing loop also includes recording/loop overhead. Raw vectors/counts and
per-process nearest-rank p50/p95/p99 are retained with sample count. Small smoke
quantiles are correctness checks, not tail estimates. Do not pool percentiles or
average them as observations; report repeated process summaries and spreads.
Throughput units are committed rows/s, rolled-back transactions/s and rejected
attempts/s; do not combine these into one ranking. Every case/caller has a
separate checked warmup. Nine seeded shuffled orders per full case give 270
principal process samples. Shared-host load/frequency remain uncontrolled.

## Policy and independent verification

Both connections use busy0, synchronousFULL, cache_size-2000,
wal_autocheckpoint1000, foreign_keysON, trusted_schemaOFF and normal locking.
Alternatives read back actual settings. Goose permanently denies PRAGMA:
a separate isolated probe links the EXACT production archive built for Goose,
proves denial, then removes its authorizer solely to read fixed PRAGMAs. Actual
Goose settings are INFERRED from adapter/options/engine identity. No public
bypass/hook is introduced. Incompatible engine defaults fail instead of weakening
policy. FULL is policy matching, not power-loss proof or storage-hardware safety.

Timed WAL work can include auto-checkpoint. Last-close cleanup is outside loop
clocks but inside process/RSS accounting. Pre/post file/sidecar state is retained;
peak WAL and causal diagnosis of individual latency tails are not measured.

Runners stream typed ordered IDs and owned payloads, verify every byte and consume
DONE after timing. The coordinator independently reopens read-only, streams the
complete oracle, checks journal/integrity, and records logical SHA256, row count,
checksum and file hashes. BUSY guard restoration/recovery insert are included.
Successful databases/sidecars are removed only after verification and hashes;
failed fixtures/diagnostics are retained. Prior outputs are never overwritten.

## Provenance and limits

HEAD/dirty state and hashes precede builds. Relevant sources are frozen to a
private snapshot; working/frozen bytes, HEAD and dirty state are rechecked after.
Fresh Goose/CMake/Rust outputs prevent stale builds. Actual Goose must match its
pin. Metadata retains source/workflow/pin/header/dependency/tool/engine/binary
hashes, actual flags/commands, filesystem/mount, CPU/OS/affinity/load, order,
timestamps and raw stdout/stderr. Public metadata normalizes private paths.

Goose caller/C++ drivers use -O2; native adapter Release -O3/-DNDEBUG. SQLiteCpp is
freshly external-engine Release -O2/-DNDEBUG. Rust uses opt-level2, Thin LTO,
16 codegen units, incremental compilation, committed Cargo.lock, no bundled
SQLite. Ambient build overrides/wrappers are cleared; nonempty loader overrides are rejected. The parent seeding/verifier mapped engine is checked against the child object.
Dependency sources, compiler/runner binaries and loaded engines are rechecked.

GNU time %M is approximate whole-child-lifetime RSS KiB including startup, setup,
verification, cleanup and small native launcher footprint. It is not incremental
heap/PSS or loop-only allocation. Parent wall/CPU includes process overhead.
Actual filesystem/mount is recorded; tmpfs/ramfs rejected. Overlay/network mounts
establish no physical-disk behavior. Device/controller caches and power-loss
behavior are unverified. Existing recovery/cold-engine TSan scope is unchanged.
No universal language/library ranking follows.

Samples flush individually to samples.jsonl. Failures/timeouts preserve owned
fixtures, stdout/stderr and incomplete/failure metadata. Timeout cleanup kills
only the owned process group. Changed source/failed runs cannot be complete.

The native probe opens two simultaneous connections, checks PRAGMA denial on
each, then reads and compares their settings only after test-process authorizer
removal. It closes both before reporting. It is never linked into the package.

Engine references: [transaction locking](https://sqlite.org/lang_transaction.html),
[synchronous policy](https://sqlite.org/pragma.html#pragma_synchronous), and
[WAL checkpointing](https://sqlite.org/wal.html#checkpointing).

Only caller order is shuffled within each fixed journal/workload block; block
order is fixed. Cross-journal differences are observational, not causal evidence.
FULL matches a configured policy, not identical power-loss behavior across modes.
The automatic_retries field counts application-level retries only.
