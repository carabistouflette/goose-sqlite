# Main-schema transaction-state validation

Implementation/test source: `746f07c12ab540b5d66fb0528fda0cb1ea4915e3`.
[Provenance](validation.json) retains source/binary/engine hashes, compiler
identities, observed exit statuses and completion excerpts. These finite checks
are not proof of safety or a performance improvement.

Public cases cover prepared/active table reads, repeated observations preserving
ROW data, reset/DONE/finalize, BEGIN DEFERRED/IMMEDIATE, READ-to-WRITE promotion,
savepoints, automatic rollback, read/write BLOBs, TEMP exclusion and stale/default
handles. A pending SELECT retains READ across COMMIT with autocommit enabled.
Native cases cover foreign/default/wrong-kind tokens, null/byte-aligned outputs,
unknown status kinds, zero failure outputs and nonzero WRITE output.

Host runner/native/isolated-import suites, GCC/Clang adapter ASan/UBSan native
checks, and SQLite 3.37 native plus runner/compiled metadata checks pass.
Anonymous full-SHA import disables global/system Git config and credential prompts.
Two independent design reviews, an implementation review and a separate final
code/contract review found no remaining blocker within their scope.

Maintained CI additionally covers full fault/recovery suites, a pinned instrumented
engine, fuzz smoke, native x86-64/ARM64 and scoped TSan. Passing TSan serializes
engine initialization; original cold-engine diagnostics remain unresolved.
No new timing or ranking follows; old benchmarks retain their original scope.
