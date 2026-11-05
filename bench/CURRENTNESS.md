# Benchmark currentness

## What the results say

The public `main` revision checked for this audit is
`70ebfc263a1d1d8714899d5ec43510076668f5b5` (tree
`6a40d4c21b10fbc66b55921237c7c309fa40e4a2`). No release tag was present at that
revision. The benchmark tables below are retained measurements of their recorded
source snapshots. They are not a current cross-library speed ranking.

The current implementation has no general performance advantage claim. The
zero-filled BLOB result has a source-level bridge to the current timed code, but
its exact compiler binary differs, so it remains a historical measurement rather
than a current benchmark claim. A current cross-wrapper performance ranking is
N/A: no retained dataset matches both current source and the exact compiler
executable. This documentation audit did not include a measurement rerun.

## Current source and tool identities

The current source uses Goose compiler revision
`eadca409f68210893f366e60d0c2f0dc29a339be`. The benchmark records name that same
compiler revision but record executable SHA256
`2bdd604d01c3f46b03ddae80871b10de7f75e9e710ce92faa1a644b246472ab7`. The
compiler used for this documentation's example checks has SHA256
`3cad45a18356bf97f4732f1da2012252afd77a652932ddb9c91c5551c04904be`. The
executables therefore do not match byte for byte.

The current host is Arch Linux x86-64, kernel `7.2.11-arch1-1-x86_64`, GCC
`16.2.1 20260810`, and SQLite `3.54.1` with source ID
`2026-10-16 14:45:20 555e07ef33f69a0957d24d8e555b702464a131d6f1607f4c3c1e4551e8e6alt1`.
The current SQLite shared object SHA256 is
`99ad85c87b9c2a461a670a1db545ca17b29d9208fe4e2887a5ff6942f2c2e61a`, matching
the recorded benchmark engine. Several records use the same measured host and
engine, but this does not make their source or executable identities current.

The zero-BLOB source bridge can be inspected without rebuilding or measuring:

```sh
git diff ead19309bef4394ffc041f079d50e2a8d78b7388 \
  70ebfc263a1d1d8714899d5ec43510076668f5b5 \
  -- sqlite.goose native/sqlite.c native/sqlite.h sqlite.build CMakeLists.txt GOOSE_REVISION
```

The differences add `transaction_state`, its native status case, and the generated
native-manifest checksum. Binding, stepping and byte-read bodies are unchanged.
This is a source check; it does not assert identical generated executables.

## Dataset ledger

| Record | Measured source | Workload and evidence | Status against current `main` |
|---|---|---|---|
| [Initial workloads](results/validated-2026-11-04/README.md) | `9ec43742e4c2cb0841b36110433a41c1c22c79f3` | 54 samples; nine fixtures, two callers, three alternating passes; whole-process wall and CPU time; all sample checksums retained. | Historical. The getter implementation and later benchmark setup changed. |
| [Buffer reuse](results/reuse-2026-11-04/README.md) | Baseline `7cf6e4adbb1dc17bd6c29ac62e0142242f0234f0`; candidate behavior `c03efc2`; separate caller record `78e906d65397cb0c9a0969fc00dab23666823e12`. | Seven alternating pairs on four copy fixtures, plus a separate 54-sample caller record. CPU time, Callgrind instruction counts, all raw samples and spread are retained. | Historical. The getter now includes later lazy-BLOB allocation handling, and the compiler executable differs. The old experiment's accepted change and its exact scope are recorded in its report. |
| [Alternative wrappers](results/alternatives-2026-11-04/README.md) | Final `a834991cc73138fd1d8c7a70a88006e55dd79f5f`; earlier valid set `8b35056659` in `before-fetch.json`. | 245 checked samples: seven fixtures, five callers, seven shuffled rounds. Loop ns/op and whole-process times are retained with raw samples and ranges. | Historical. Current getter code and benchmark harness differ. The result page preserves the old values and its Rust build-profile correction. |
| [Realistic workloads](results/workloads-2026-11-04/README.md) | Final `e24de8ce7495c8146c6c9b408cf08686c981c182`; earlier records are linked from the report. | 350 final samples, 350 before-registry samples and 140 matched registry samples; ten fixtures, five callers, seven shuffled rounds. Loop ns/op, RSS and raw samples are retained. | Historical. The getter implementation changed after the record. Do not use its tables as current-source rankings. |
| [Row cache experiment](results/row-cache-2026-11-04/README.md) | Baseline `4e13128`; rejected candidate `c7a04ded8eb8e67f2545c5dc84137338ac2402cb`, reverted by `aa0f466`. | 180 checked samples across ten fixtures; paired ratios and observed ranges are retained. Callgrind data is instruction count, not elapsed time. | Historical, rejected diagnostic. The candidate is not current production code. |
| [Incremental storage](results/storage-2026-11-04/README.md) | Handoff `b01179509d63a7e5e73b0de11de03dad4e2a81d2`; overlap `d030ad327b833b76dcf8969b25b4f3b1d443708a`. | Each window has 144 samples: nine rounds, four sizes and four paths. The report retains units, ranges, source/build identities and the original CPU7 overlap disclosure. | Historical comparison. The whole-column getter changed after both runs; the incremental API path is unchanged. No present-day whole-versus-incremental timing claim follows. |
| [Zero-filled BLOB binding](results/zeroblob-2026-11-05/README.md) | `ead19309bef4394ffc041f079d50e2a8d78b7388`. | 270 timing samples and 30 allocation probes over 45 shuffled six-path rounds; medians, observed ranges and raw data are retained. | Source-bridged snapshot only. The timed binding/read code is unchanged: the later native diff adds a separate transaction-state status case, and the Goose diff adds that status API. The benchmark's compiler executable hash differs from the available build, so its timings are not a current ranking or rerun. |
| [File-backed transactions](results/filebacked-2026-11-05/README.md) | `52dca0d4f3d5718b5f7c4c586249d7404c80f783`. | 270 process samples, 34,560 operation latencies and 30 warmups; six transaction/BUSY cases. Tables retain per-process latency quantiles, throughput and RSS with observed spreads. | Historical. The compared file-backed harness, wrappers and build setup changed. The result remains valid for its frozen snapshot only. |
| [Coordinated WAL reader/writer pairs](results/mixedwal-2026-11-05/README.md) | `8133274b6df6b63c27a3ef541a0539f1f7984d10`. | 50 pairs, 6,400 writer commits and 69,359 checked snapshots; per-role latency, rates, RSS and raw logs are retained. | Historical coupled-workload snapshot. The recorder changed its parent/actor input handling, which can affect scheduling. It does not establish isolated API overhead or a current ranking. |
| [Scan/copy profile](results/scan-copy-2026-11-05/README.md) | Baseline `a90d281`; rejected candidate `4b22116`. | Callgrind instructions for three fixtures, exact sources and compressed raw profiles retained. | Historical, rejected diagnostic. It measured instruction counts, not native throughput; production behavior was left unchanged. |

Each linked result report gives its full command, workload units, warmups,
repeats, compiler and dependency versions, machine details, timing boundaries,
checks, observed spreads and raw artifact paths. Raw JSON and profile artifacts
are preserved as recorded; this audit changes no measurement data. The shared
host, affinity and frequency limits in those reports still apply.

## Reading and reproducing results

Use a result only for the exact recorded source and toolchain described in its
report. A source bridge can show that a specific measured code path is unchanged;
it does not make the old executable, compiler, build archive, or host run identical
to current `main`. Reproduce a result with its exact source and tool versions in
a finite series. A short smoke run checks the harness and is not performance
evidence.
