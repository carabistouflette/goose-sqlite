# Contributing

Keep the interface small, synchronous, explicit, and easy to audit. Preserve
validation, typed reads, copied ownership, thread affinity, and stale-token
safety. No ORM, generic backend abstraction, hidden global connection, implicit
transaction, or automatic statement reexecution. SQLite is a required native
dependency; a pure Goose fallback is out of scope.

Use focused branches (`feat/...`, `fix/...`, `docs/...`) and Conventional Commits:
`feat: add ...`, `fix: reject ...`, `test: cover ...`, `perf: reduce ...`,
`docs: clarify ...`, `chore: update ...`. Use imperative subjects and one coherent
change per commit. Keep private workspace notes, credentials, generated compiler
output and local paths out of public commits.

Behavior changes need public interface regression cases. Run `make format`,
`make check test`, native GCC/Clang sanitizer tests, and `git diff --check`.
Refresh the native fingerprint with `make format`. Request independent reviews
at design, implementation and final validation milestones; fix actionable
findings before publication. Compiler updates require a reviewed full commit
in GOOSE_REVISION and full validation. Keep CI passing. APIs are experimental;
no stability guarantee before 1.0.

Profile before optimizing. Preserve safety checks and retain raw measurements
with source, compiler, SQLite, hardware and flags. Report all fixtures and
regressions; shared-machine microbenchmarks do not establish universal rankings.
Report vulnerabilities privately as described in SECURITY.md.
