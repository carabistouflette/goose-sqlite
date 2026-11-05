# Independent SQLite performance audit

> Historical source and compiler snapshot; the separate caller record below is also not a current-source ranking. See the [currentness audit](../../CURRENTNESS.md).

Baseline commit `7cf6e4adbb1dc17bd6c29ac62e0142242f0234f0`. Pinned Goose compiler and captured source/binary provenance are in `provenance.json`. This directory retains all raw timing samples; bulky Callgrind dumps and generated binaries are not committed.

## Recommended minimal change

Defer the initial `out.clear()` in `column_bytes`: keep existing length through native_size; clear on size/limit failure; then resize and native_copy; retain copy-error clear. Owned successful output and empty-on-error behavior remain intact. Same-length/shrinking outputs avoid redundant zero fill. Native adapter/API/ownership/validation are unchanged.

## Matched measurement

Seven alternating baseline/reuse runs, CPU2 affinity, byte equality assertions active. No native or fixture changes. Whole-process medians below, including open/close and process startup. Shared host, no fixed frequency or exclusive CPU; fixture speedups are observations, not broad performance claims.

| Fixture | Iterations | Baseline median CPU ms | Reuse median CPU ms | CPU change |
|---|---:|---:|---:|---:|
| text 32 bytes | 1000000 | 384.430 | 385.578 | +0.3% |
| text 4096 bytes | 500000 | 507.283 | 475.920 | -6.2% |
| text 65536 bytes | 100000 | 1377.805 | 1127.474 | -18.2% |
| blob 1048576 bytes | 10000 | 2757.918 | 2526.373 | -8.4% |

Raw samples and sampling loop: `samples.json`, `compare.py`; copied packages and generated C were inspected during review but are not committed. The generated C confirms original clear forces zero fill every iteration, whereas candidate fills only newly grown suffixes.

## Profiles and scope

* Callgrind `callgrind.text32`: 100000 text32 iterations on the previously verified benchmark executable. gq_size inclusive 19.15%, gq_copy inclusive 14.52%, gq_step inclusive 39.23% instruction refs. Percentages overlap through callees; these are instruction references, not timing shares.
* Callgrind `callgrind.blob1m`: isolated baseline, 1000 1MiB BLOB iterations. memcpy 53.57%, fixture memcmp 32.29%, memset 13.31% self instruction refs. Byte-checking is substantial, so these fixtures are checked round-trip workloads rather than pure column-copy throughput.
* Callgrind `callgrind.prepare`: isolated baseline, 10000 iterations, sqlite3_prepare_v3 inclusive 79.82% instruction refs. Statement reuse is a caller workload decision; no basis for adapter complexity.
* Callgrind `callgrind.insert`: isolated baseline, 10000 iterations, sqlite3_step inclusive 83.61% instruction refs. No basis for native validation/registry shortcuts.
* perf sampling was unavailable with current host perf_event policy; no sampling time profile is claimed. Callgrind is deterministic instruction profiling and does not measure real memory bandwidth/caches.

## Benchmark follow-up

If deferred-clear is adopted, move C baseline output memset outside the loop so it initializes only once like Goose. Update methodology wording. Existing historical evidence should retain its old source hashes. Keep every-byte correctness validation. Recommend adding a read-only/prebound row scan later only if real workload investigation needs fetch costs separated from bind-copy/reset; current fixtures include input ownership copies, SQL stepping and validation.

The two-call native_size/native_copy interface has measurable duplicate column checks in the small-text fixture, but changing it would add API/ownership complexity. The simple deferred-clear improvement has direct measured support without that cost. No two-call redesign recommended.

## Reproduce and interpret

The recorded baseline is the commit above. The candidate behavior matches
`c03efc2` (only an unrelated comment differs from the measured copy). Export or
clone both source revisions into separate directories, build each
`bench/bench.goose` with the pinned compiler and `-O2`, a fresh GOOSE_HOME, and
identical host compiler/SQLite settings. Name the executables `baseline-bin` and
`reuse-bin` beside compare.py. The captured sampling loop pins CPU2; coordinate
that core or deliberately change the affinity before replay. It checks every
process checksum; benchmark binaries also compare every output byte.

Native archive hashes are identical between the original variants. Captured
CMake compile flags are in provenance.json. Shared-library hashes were captured
after the completed series, with measured executable hashes reverified; this is
not proof that system libraries or other host state were immutable during timing.
Callgrind summaries describe instruction references, not elapsed-time percentages.
No claim of complete environment reproduction or statistical significance follows.

The maintained C baseline now initializes output once outside its fixed-size loop,
matching the committed Goose reuse path. Historical records retain their original
source hashes. Allocation strategy differs between callers; these checked
round-trip measurements do not establish pure fetch throughput or a general ranking.

## Maintained caller benchmark

[current-callers.json](current-callers.json) retains a separate 54-sample
three-pass run on clean commit `78e906d65397cb0c9a0969fc00dab23666823e12`. It
uses the updated C initialization policy, both callers' identical checked native
archive/runtime SQLite, all nine maintained fixtures and their checksums. It was
pinned to CPU6 while other validation work ran elsewhere. Interpret it as a
shared-host checked workload record, not an isolated throughput measurement.
