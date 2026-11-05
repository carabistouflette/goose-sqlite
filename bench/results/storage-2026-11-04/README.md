# Incremental BLOB ranges: measured results

> Historical source snapshot. The whole-column getter changed after these runs; see the [currentness audit](../../CURRENTNESS.md) before interpreting the table.

Two complete datasets, each 144 checked samples: nine shuffled rounds, four range
sizes and four API paths, 20000 iterations per sample. Stored value 512 KiB,
private in-memory databases, held read transaction, deterministic changing offsets,
reused owned outputs, all requested bytes verified inside the timed region.
Both APIs also verify the whole fixture before timing. Setup/lifecycle is excluded.

[handoff.json](handoff.json) is the separate series after CONFIG released CPU7.
[overlap.json](overlap.json) is the first series, retained unmodified, with a known
concurrent CONFIG series on CPU7. The verified parent starts were CONFIG 13:39:27Z
and SQLite 13:39:34Z. Both ran normally to completion. [Overlap notes](overlap-notes.json)
and [handoff notes](handoff-notes.json) retain boundaries and shared-host caveats.
No exclusive core, fixed frequency, controlled cache or isolated host is claimed.
Other SQLite validation used CPU6 and a source build used CPU5 during the handoff.
Do not describe absolute differences between the two windows as a controlled gain.

## Handoff series: median [minimum–maximum], µs/operation

Lower is faster. Whole paths copy 512 KiB every operation, then compare the selected
range. Incremental paths copy/compare only that range. Raw C explicitly copies
into reusable owned storage; the compiler retained the 512 KiB memcpy in its loop.

| Requested range | Goose whole | Goose incremental | SQLite C whole | SQLite C incremental |
|---|---:|---:|---:|---:|
| 64 B | 14.842 [14.296–20.032] | 0.049 [0.042–0.059] | 15.695 [14.353–18.163] | 0.036 [0.034–0.040] |
| 4 KiB | 14.877 [14.105–16.281] | 0.327 [0.306–0.352] | 14.642 [13.781–15.031] | 0.318 [0.302–0.355] |
| 64 KiB | 16.223 [15.756–20.402] | 4.831 [4.600–7.267] | 17.644 [15.717–22.419] | 4.776 [4.502–5.202] |
| 512 KiB | 32.497 [27.147–65.033] | 47.596 [35.908–77.119] | 36.860 [27.023–66.111] | 36.882 [34.194–82.210] |

For 4 KiB requests, Goose medians are 14.877 µs whole versus 0.327 µs incremental
(whole/incremental median ratio about 45.5× in this window); raw C incremental is 0.318 µs.
The 512 KiB whole copy is 128× as many **bytes copied to output** as a 4 KiB range.
Both benchmark processes preallocate 512 KiB output in preflight: no allocation,
SQLite heap, RSS, disk I/O or storage-size reduction is established by this run.

For a full 512 KiB value, Goose incremental median 47.596 µs exceeds whole-column
32.497 µs (about 46% higher); use column_blob for full-value reads. That fixture
also has wide sample spread. Neither this comparison nor source inspection
establishes a universal wrapper ranking. Both C and Goose can choose incremental
access; this is a useful API/amount-of-copying benefit, not a faster SQLite engine.

## Provenance and policy

Measured native source is unchanged between the two windows (same archive hash).
Handoff source is clean b01179509d63a7e5e73b0de11de03dad4e2a81d2; original source is
clean d030ad327b833b76dcf8969b25b4f3b1d443708a. Source/binary/archive and Goose compiler hashes, compiler versions/flags,
SQLite source ID/options and the matching loaded engine hashes,
raw stdout/checksums, process CPU/wall clocks, load and affinity are in each JSON.
The first record omitted a separate native compiler identity; its note discloses
that limit. The handoff harness records the actual native compiler version/hash.

Goose/raw callers use GCC -O2; the native production adapter uses CMake Release
-O3 -DNDEBUG, with validation intact. Raw checks stay active. Goose compiler is
pinned at eadca409f68210893f366e60d0c2f0dc29a339be. Both load the same SQLite 3.54.1
shared object (distribution alt1 source ID). Goose retains hardening, token checks
and bounded policies; raw C uses NOMUTEX/private-cache engine defaults. There is
no identical-policy claim. The [methodology and reproduction command](../../storage/README.md)
explain timing boundaries. The [five-wrapper comparison](../alternatives-2026-11-04/README.md)
remains a separate seven-fixture dataset; no Python/Rust/C++ incremental timing is
invented here. Feature differences remain explicit in [the comparison](../../../docs/alternatives.md).
