# Contributing

Keep the API small, synchronous, explicit and easy to audit. Preserve typed
reads, copied byte ownership, thread-affine handles, stale-handle checks and
explicit error handling. Do not add a pool, implicit transaction, hidden global
connection or automatic statement retry.

Use a focused branch and one Conventional Commit per coherent change. Keep
generated files, private notes, credentials and local paths out of public commits.
Behavior changes need regression tests. Run make format, make check test, native
GCC/Clang sanitizer checks, and git diff --check when they apply. Update the native
manifest with make format.

For compiler changes, review the full Goose commit in GOOSE_REVISION and run the
complete validation suite. Request independent reviews for design and behavior
changes and resolve actionable findings before publication.

Profile real workloads before optimizing. Keep raw benchmark samples with source,
compiler, SQLite, platform, flags and workload details. Report all cases and
regressions. Shared-host results are not universal rankings or CI thresholds.
Report vulnerabilities privately as described in SECURITY.md.
