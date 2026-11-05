# Zero-filled BLOB API comparison

```sh
python3 bench/zeroblob/measure.py --goose /path/to/pinned/goose \
  --iterations 32768 --runs 9 --cpu 6 --output .build/zeroblob-results
```

Choose and coordinate an available core or omit `--cpu`. Requires the pinned
Goose compiler, GCC, CMake, Python 3, GNU time and installed SQLite development
files. Output must be empty; previous evidence is never overwritten.

Six paths compare Goose and raw SQLite C across three APIs: copying a prepared
zero buffer with `bind_blob`, binding its length with `bind_zeroblob64`, and the
existing SQL `SELECT zeroblob(?1)` with an integer binding. The first two use
identical `SELECT ?1` statements. The SQL control prevents attributing an existing
engine optimization exclusively to the new binding.

All paths use private in-memory connections, reuse a prepared statement, require
BLOB storage and exact length, copy into owned output, check every zero byte,
consume DONE and check reset. Only copy mode allocates its input template, outside
timing. Every output is preallocated. The same statement is primed before timing;
separate warmup processes are also checked. Timing includes bind, step, copy,
every-byte verification, DONE and reset; connection, statement and buffer creation
and cleanup are excluded. Strict BLOB reads get byte count before materialization,
and skip pointer materialization entirely for zero length in both bindings.

Sizes are 0, 4 KiB, 64 KiB, 512 KiB and 1 MiB. Per-case iterations are
`max(1, base_iterations*4096/max(size,4096))`. At the default count, each nonzero
sample verifies about 128 MiB, across nine seeded shuffled rounds per size.
Each process reports loop nanoseconds and checksum `iterations*(size+1)`, adding
one for every completed row so even empty cases independently check iteration
count. Every byte is still verified. Empty BLOBs remain distinct from NULL. This SELECT workload does not
claim that a 1 MiB BLOB fits an encoded persistent row under the binding's 1 MiB
engine limit.

Relevant working-source bytes are frozen in an isolated build, with a checked
native manifest and fresh Goose package cache. Commit/dirty state and all source
hashes are captured before build; relevant source or HEAD changes afterward fail
the series. Principal results should use committed, clean source. Dirty development
smokes are labeled by their metadata. All three executables must load the same
SQLite shared-object hash; the diagnostic reports explicit engine identity/options,
inferred for Goose from its matching loaded object. Actual Release native flags,
archive/generated-source/toolchain/binary/header hashes, shuffled order, timestamps,
host load and affinity are retained. Completed samples are flushed individually;
failures and incomplete metadata cannot produce a completed result. Child timeouts
reap only the owned process group. Build artifacts remain ignored under `.build`.

GNU time records whole-process peak RSS, including setup, priming, verification
and small native launch footprint. This is not incremental or per-binding heap.
Goose retains its token/type/state/security policies; raw C uses always-on checks,
NOMUTEX/private-cache connections and otherwise ordinary engine policy. The paths
are not identical policies. Both bindings can avoid copying the source zero buffer
through either zero API; this does not make SQLite itself faster. No disk-write,
durability, WAL, contention or incremental-BLOB-write ranking follows.

Separate native diagnostic processes enable SQLite allocator accounting before
initialization, prepare one statement, and sample `sqlite3_memory_used` immediately
before and after binding, before step/materialization. Both raw C and the checked
native ABI are probed. All bytes are then read and verified, resources close and
SQLite shuts down cleanly. These deltas exclude source/output malloc and the Goose
runtime heap. They describe the engine's binding representation, not total BLOB
or process memory: reading or storing zeroblobs can still allocate their contents.
