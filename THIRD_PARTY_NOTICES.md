# Third-party dependencies

This repository's code is Apache-2.0 (LICENSE). No SQLite implementation is
vendored. Builds link the installed SQLite development/runtime library (3.37+).
SQLite's core is [public domain](https://sqlite.org/copyright.html); downstream
packages and optional extensions may have additional notices. Inspect your
operating-system package for its exact version, configuration and notices.

The pinned Goose compiler is fetched from https://github.com/aardappel/goose
by scripts/setup-goose.sh. Its code and bundled dependencies retain their own
licenses and notices in that checkout; generated toolchain files are not
redistributed as part of this source repository. pthreads and libc come from
the host platform and retain their platform licenses.

## Optional comparison harness

The alternative benchmark downloads SQLiteCpp3.4.0 (MIT) at its recorded full
commit and builds rusqlite0.41.1 (MIT) with the checked-in Cargo.lock. Their source
and dependency notices remain in their fetched checkouts/crate sources; none is
vendored into this library or linked into its production adapter. Python sqlite3
uses the installed Python runtime (PSF license and historical notices). See
[the cited comparison](docs/alternatives.md) for first-party license/source links.
Generated comparison executables are ignored build artifacts, not source releases.

The optional validation script scripts/test-wal-engine.py downloads SQLite 3.54.1
into ignored build output, verifying a pinned archive SHA-256 and the upstream
sqlite3.c SHA3-256 from its release record. That test-only engine is compiled with
ASan/UBSan or separately TSan, with DEFAULT_WAL_SYNCHRONOUS=1, to exercise
positive WAL behavior on CI;
it does not replace or vendor the production system dependency. SQLite is in the
public domain: https://sqlite.org/copyright.html .
