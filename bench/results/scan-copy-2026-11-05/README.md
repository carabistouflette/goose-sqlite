# Scan/copy profile and rejected resize experiment

> Historical Callgrind diagnostic for a rejected candidate. Instruction counts are not current throughput results. See the [currentness audit](../../CURRENTNESS.md).

Decision: retain the production implementation from
`8a1d0d74f731d07d16cfd693cf6ce16105d20253`. Skipping the final equal-length
builder resize did not provide a consistent instruction reduction. The candidate
was reverted; no native timing campaign or speedup claim follows.

## Frozen experiment

The baseline is `a90d281` (adds the profiler only); candidate `4b22116` adds
`if size != out.len` around the final `out.resize(size)`. Full commits and all
source hashes are in each metadata file and were verified against Git blobs.
The original native code, strict types, ROW/index/thread/token checks, copied
ownership, output failure clearing and lazy/empty BLOB OOM handling are unchanged.
The public API regression suite passed on the candidate. Two independent
reviewers assessed profiling/design and recorder provenance; candidate safety
was reviewed separately from its performance value.

Whole-process Callgrind **executed instructions**, including setup and every-byte
verification. These are not CPU cycles, native timings or confidence intervals.

| Fixture | Baseline Ir | Candidate Ir | Candidate minus baseline |
|---|---:|---:|---:|
| Scan: 100 passes × 1024 rows × 128 B | 142781247 | 142678900 | -102347 |
| Indexed lookup: 10000 × 128 B | 46006745 | 46016798 | +10053 |
| Text bind/copy: 10000 × 4096 B | 46800931 | 46811002 | +10071 |

The scan reduction is small and the other paths increase. This fails the first
acceptance gate; it does not establish a native speed regression either. No
same-source A/A timing control or wall-time significance test was performed.
Instrumented clock values remain in raw stdout solely as diagnostics.
[summary.json](summary.json) records exact values and the decision.

## Profile interpretation

In the baseline scan, engine step is about half the inclusive instruction count.
The native fetch helper is 5.95% self, integer getter 3.87%, column-count query
0.72%, and byte equality 7.39%. Self and inclusive percentages describe different
scopes; inclusive functions overlap and cannot be summed. These are whole-process
figures, not loop-only attribution. Text copy/verification remains substantial;
its setup and owned input binding are also included.

Disassembly shows one token lookup, state/index/type checks, bounded length and
materialization checks, and one native output copy. The generated caller already
inlines the final resize. There is no demonstrated redundant native copy or
clearing operation to remove. The [earlier width-cache experiment](../row-cache-2026-11-04/README.md)
remains rejected. Neither result justifies weakening safety checks or adding
cache state or a larger row interface.

## Evidence and reproduction

[baseline/metadata.json](baseline/metadata.json) and
[candidate/metadata.json](candidate/metadata.json) retain source/Git object hashes,
actual native build/compiler/flags, generated caller/archive/binary hashes, Goose
pin and binary identity, loaded engine identity/options, OS/CPU, tool hashes,
checksums and completion state. CPU6 affinity is shared-host scheduling, not
exclusive isolation. Goose caller uses GCC -O2 and the native adapter Release
-O3/-DNDEBUG. All fixtures use the same installed SQLite 3.54.1 object.

Each directory retains compressed raw Callgrind data, self/inclusive annotations,
stdout/stderr and fetch disassembly. Only checkout/compiler-checkout prefixes
are normalized, with original and retained hashes recorded; gzip is deterministic.
The [exploratory record](exploratory/metadata.json) retains the earlier one-off
profile too: its text count is 1000, versus 10000 in the principal experiment.
It is separate evidence and is not silently substituted into the table.

```sh
python3 bench/alternatives/profile.py --goose /path/to/pinned/goose \
  --ref a90d281 --cpu 6 --output .build/profile-baseline
python3 bench/alternatives/profile.py --goose /path/to/pinned/goose \
  --ref 4b22116 --cpu 6 --output .build/profile-candidate
```

Requires Linux, Valgrind/Callgrind, binutils, GCC and normal project build
requirements. Choose an allowed core or omit affinity. Output must not already
exist. Fresh snapshots/caches are checked against Git before/after execution;
compiler identity is checked against the declared pin. Failures preserve incomplete
metadata and cannot produce a completed result. The maintained recorder has
provenance improvements over the original exploratory script.
