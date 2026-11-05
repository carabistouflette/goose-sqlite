# Row scan profile and rejected cache experiment

> Historical diagnostic for a rejected candidate. It does not describe current production performance. See the [currentness audit](../../CURRENTNESS.md).

The lazy per-row column-count cache was **rejected**. Nine matched pairs across
all ten fixtures give mixed medians and wide shared-host spreads. The evidence
does not justify extra cache state or establish statistically significant gains
or regressions. Final production getters and step remain unchanged.

## Matched loop results

180 checked samples, one million requested iterations per sample; scan uses
976 complete 1024-row passes and large text uses one tenth of the count.
Ratios are before/after loop time: above 1 favors the candidate. This table reports
every fixture, including unfavorable medians. Min/max is the observed pair range,
not a confidence interval. Candidate-favored pair counts do not establish significance.

| Fixture | Median ratio | Minimum–maximum | Candidate favored |
|---|---:|---:|---:|
| prepare | 1.0119 | 0.9492–1.0726 | 6/9 |
| scalar | 0.9938 | 0.9728–1.0181 | 2/9 |
| text32B | 0.9741 | 0.9351–1.0038 | 1/9 |
| text4096B | 0.9725 | 0.9384–1.0076 | 2/9 |
| text65536B | 1.0232 | 0.9569–1.0692 | 5/9 |
| blob4096B | 0.9611 | 0.9200–1.1296 | 4/9 |
| insert | 1.0153 | 0.9362–1.1282 | 5/9 |
| scan128B | 1.0356 | 0.9587–1.1504 | 6/9 |
| lookup128B | 0.9864 | 0.8262–1.1674 | 4/9 |
| batch128B | 0.9603 | 0.9037–1.1346 | 4/9 |

The parent ran 2026-11-04T22:47:31.119166Z–22:50:08.520088Z on CPU 4, 157.4009 s
including builds/warmups. CPU 4 was coordinated and released after completion.
Other-library correctness jobs were observed on other affinity sets; the host,
frequency, shared caches and load were not isolated. No existing job was stopped.

[samples.json](samples.json) retains all samples, pair ratios, frozen Git object
identities, source/build/binary/tool/engine hashes, actual compiler flags, affinity,
load and timing scope. [samples.jsonl](samples.jsonl) preserves the flushed sample
journal; [metadata.json](metadata.json) is the metadata-only counterpart.
[summary.json](summary.json) records all medians/ranges and retained-file hashes.
No principal sample failed or was dropped. The earlier 20-sample run was a harness
smoke and supplies no performance conclusion.

Before source 4e13128, candidate c7a04ded8eb8e67f2545c5dc84137338ac2402cb,
reverted by aa0f466. Complete object IDs are in the metadata. Both sources include
the startup/checkpoint features and identical timed fixture code; only the candidate
adds ROW width caching. Snapshots are verified against Git blobs before and after;
the working checkout is not the timed source. The harness itself was committed
and unchanged. Native Goose executables are measured; the dynamic runner has no
matching speed claim.

Goose is pinned at eadca409f68210893f366e60d0c2f0dc29a339be. Both builds use the
same actual GCC 16.2.1 and SQLite 3.54.1 object/source/options; Goose uses -O2 and its
native adapter uses recorded Release -O3 -DNDEBUG. Two independent caches prevent
source/package reuse. Owned copies, strict type/state/thread/token checks, all
payload bytes, SQL plans and operation counts remain unchanged. GNU time RSS is
whole-process peak KiB, including setup/verification and small native-launch
footprint; it is not incremental binding memory. There is no universal ranking.

## Instruction profile

The prior frozen c9a64c4 profile has the same column getter hot paths as the
experiment baseline. 100 scan passes × 1024 rows × 128 owned/verified BLOB bytes give
checksum 13107200 and 142473265 whole-process Callgrind instructions. Column-count
calls account for 0.72% self instructions; this is not wall-time attribution.
The profile suggested a modest candidate rather than a bulk API or unsafe
unprotected-value getters. [profile.json](profile.json) retains source/compiler/
engine/flags and raw/normalized hashes. [scan.callgrind](scan.callgrind),
[scan-self.txt](scan-self.txt) and [scan-inclusive.txt](scan-inclusive.txt) replace
only the repository checkout prefix with $REPO; diagnostic data is otherwise retained.

## Reproduce

From a full checkout, with the pinned Goose compiler available:

```sh
python3 bench/alternatives/paired.py --goose .toolchain/goose/build/goose --before-ref 4e13128 --after-ref c7a04de --iterations 1000000 --runs 9 --cpu 4 --output .build/cache-reproduction
```

Choose/coordinate an available core or omit --cpu. This builds frozen revisions
without changing an index or checkout. Output must be empty; prior results are
never overwritten. Sources, binary/tool hashes and checksums are verified, errors
are retained and incomplete runs cannot supply a completed result. The maintained
CI self-comparison is only a correctness smoke, with no timing threshold.
