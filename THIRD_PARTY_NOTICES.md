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
