# SQLite alternatives: measured API paths

> Historical source and compiler snapshot. The comparisons below describe these measured builds only, not the current Goose revision. See the [currentness audit](../../CURRENTNESS.md).

Seven shuffled rounds, seven fixtures, five implementations: 245 checked samples.
All five use the same SQLite 3.54.1 shared-library hash; source-ID/compile-options
checks are explicit for four callers and inferred from that exact shared object
for Goose. Ordinary fixtures run500000 iterations; 64KiB text runs50000.

## Provenance correction — read before raw data

[errata.json](errata.json) corrects the original requested Rust lto=false field:
Cargo's user configuration overrode it with **Thin LTO,16 codegen units**, and
incremental compilation was enabled. These measured builds used opt-level2.
The raw JSON remains unchanged; the current harness explicitly enforces this
observed profile. See Cargo's [profile precedence](https://doc.rust-lang.org/cargo/reference/profiles.html).

The final record's source_dirty=true reflects only untracked stored result files.
Tracked measured source was clean; all recorded source hashes remain available
at the recorded commit. The initial before-fetch dataset was fully clean.

## Median loop wall time, ns/operation (lower is faster)

| Fixture | Goose | SQLite C API | SQLiteCpp | rusqlite String/Vec | Python sqlite3 |
|---|---:|---:|---:|---:|---:|
| prepare | 1769.0 | 1563.0 | 1207.5 | 1235.3 | 3638.1 |
| scalar | 183.6 | 128.4 | 136.0 | 155.1 | 1588.7 |
| text 32B | 248.5 | 176.7 | 227.0 | 239.7 | 1792.5 |
| text 4096B | 1032.0 | 694.7 | 773.6 | 1257.9 | 3317.8 |
| text 65536B | 13664.1 | 9995.8 | 9687.8 | 67200.3 | 21511.7 |
| blob 4096B | 779.1 | 737.8 | 783.4 | 787.4 | 2988.9 |
| insert | 323.4 | 293.9 | 299.5 | 303.2 | 1101.6 |

Goose beats this Python path in all seven fixtures. It remains slower than the
thin native wrappers on most small operations; it is close on inserts and4KiB
BLOBs, and faster than rusqlite's owned String path on the large text fixtures.
This is not an identical-policy comparison: Goose retains its checked tokens,
strict value types and bounded connection policy. Rust String validates UTF-8;
Goose/raw C/SQLiteCpp copy byte text without that independent validation. This
semantic difference is real, but source inspection alone does not attribute the
entire64KiB outlier to it. No universal performance or feature ranking follows.

Every selected payload is verified byte-for-byte inside the timed loop; insert
count and sum are checked afterward. Primary clocks exclude startup/open/setup;
whole-process CPU/wall times are also retained. Python uses normal Unicode text
and primed SQL caching except the explicitly uncached prepare fixture. Raw C API
uses a C++ driver and owned std::string copies; alternative allocation strategies
are not identical. The full methodology is [here](../../alternatives/README.md).
No disk durability, WAL, contention or portability timing is claimed.

[samples.json](samples.json) retains final bounded-fetch results;
[before-fetch.json](before-fetch.json) retains all earlier valid results, not just
wins. Do not compare absolute medians across these time windows as a controlled
speedup: host load/frequency differed. [fetch-matched.json](fetch-matched.json)
is a separate five-pass alternating Goose-only before/after prototype check,
with full byte validation. It motivated the one-call reusable-buffer path;
all validation and first/growing-buffer fallback checks remain.

The matched prototype lacked complete standalone provenance and is supporting
evidence, not the principal alternative comparison. Principal datasets include
source/compiler/interpreter/wrapper/binary/engine hashes and all raw samples.
An earlier attempt stopped on the default VM budget during untimed aggregate
verification; no complete result was published from it. The maintained runner
requests100M instructions per call for that verification and journals each sample.

The machine was shared. CPU7 affinity was nonexclusive; clocks/frequency and
other work were not controlled. All rounds, spreads and regressions must be
considered. The two other Goose bindings have separately bundled engines and
remain feature/source comparisons rather than entries in this matched-engine
experiment. See [practical feature parity](../../../docs/alternatives.md).
