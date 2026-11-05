# Third-party notices

This repository's code is licensed under Apache-2.0; see [LICENSE](LICENSE).
SQLite is a required system dependency and is not included in this repository.
SQLite is public domain. Check your operating-system package for its version,
build options and notices.

The setup script fetches the Goose compiler from
[aardappel/goose](https://github.com/aardappel/goose) at the full commit in
[GOOSE_REVISION](GOOSE_REVISION). The compiler and its bundled dependencies keep
their own licenses. They are build tools and are not redistributed here. The host
also supplies libc and pthreads.

## Optional comparison benchmarks

The optional comparison harness fetches SQLiteCpp 3.4.0 and rusqlite 0.41.1 at
the recorded revisions and uses the installed Python runtime. None of these
projects is vendored into or linked by the production adapter. Their licenses and
source references are listed in [the comparison notes](docs/alternatives.md).

The optional WAL test downloads a checksum-verified SQLite 3.54.1 source archive
to ignored build output. It is a test engine, not a replacement for the system
dependency. A separate mixed-WAL smoke also builds a normal engine from that
verified source; neither engine is part of the published source package.
