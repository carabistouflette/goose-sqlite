# Whole-column versus incremental BLOB reads

```sh
python3 bench/storage/measure.py --goose /path/to/pinned/goose \
  --iterations 20000 --runs 9 --cpu 7 --output .build/storage-results
```

The CPU is optional and nonexclusive; choose one appropriate for your machine.
Four paths run in shuffled order: Goose whole-column owned copy, Goose incremental
owned range, raw SQLite C whole-column owned copy, raw C incremental owned range.
Every path stores the same deterministic 512 KiB BLOB in a private in-memory
SQLite database, begins a read transaction, and verifies the full fixture through
both APIs before timing. Whole paths hold a SELECT at ROW; incremental paths hold
a read-only BLOB. Resource opening/cleanup is outside the timed region.

Ranges are 64 B, 4 KiB, 64 KiB and the full 512 KiB. Offsets follow
`(iteration * 4093) % (524288 - range_size + 1)`. All selected bytes are compared
with the original fixture inside the timer and byte-count checksums are validated
per process. Whole paths copy all 512 KiB into reusable owned output each time,
then compare the selected range; incremental paths copy/compare just the range.
Whole outputs are also verified in full after timing. No per-iteration buffer
allocation is required. Goose resizes/reuses its array; raw C reuses malloc storage.

This measures an application choosing a more suitable API. Both bindings can use
incremental access; there is no exclusive Goose optimization. A 4 KiB range uses
128 times fewer application output bytes than a 512 KiB value, but this does not
establish a 128-fold timing gain, bound SQLite's internal memory, or measure disk
reads, RSS, WAL, durability, contention or lifecycle overhead. Copying from a held
ROW also avoids repeated query/step work; this deliberately gives the whole path
a favorable cached source.

Goose retains checked thread-affine tokens, bounds and production policies. Raw C
uses engine defaults with NOMUTEX/private cache and always-on checks. The harness
builds fresh Goose/native caches, enforces one identical loaded SQLite library
hash, retains C engine version/source ID/options and infers Goose identity from
that shared object. Compiler/native/binary/source hashes, all raw samples, order,
checksums, load, nonexclusive affinity, and whole-process CPU/wall times are stored.
The loop clock excludes runtime startup, fixture generation, connection setup and
preflights; whole-process clocks include them. Failed commands/checks abort and
leave the journal of already completed samples. Performance is not a CI threshold.
