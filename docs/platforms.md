# Platforms and requirements

Tested platforms are Linux x86-64 and Linux ARM64. Hosted CI uses Ubuntu 24.04.
macOS, Windows, other libc implementations and other architectures are
unverified. The adapter uses POSIX threads and a thread-safe system SQLite
library.

## Build requirements

- Git, Make, Python 3 and CMake 3.27 or newer to build the pinned Goose compiler.
- A C++20 compiler for Goose and a C11 compiler for the native adapter.
- SQLite 3.37 or newer development headers and library, pkg-config, pthreads,
  and libc development headers.
- Clang plus sanitizer and libFuzzer support only for optional sanitizer and
  fuzz checks.

Run make setup to build the exact compiler commit in
[GOOSE_REVISION](../GOOSE_REVISION). To use an existing compiler at that commit,
pass GOOSE=/path/to/goose to Make. Compiler and SQLite caches are local build
outputs; they are not included in the source package.

## SQLite requirements

SQLite 3.37 is the minimum for the base API. Use a security-supported package
from your operating system. Compile-time options may remove features or impose
tighter limits. The engine must be thread-safe; the application must not set
SQLite's global mode to single-thread.

Optional WAL support is limited to recognized SQLite versions with the WAL-reset
fix: 3.51.3 or newer, 3.50.7 through 3.50.x, and 3.44.6 through 3.44.x. Other
versions fail closed when WAL is requested or already active, including unknown
backports. Every process using that database must use a fixed engine. WAL also
requires a suitable local filesystem and correct sidecar-file permissions.
Rollback-journal mode remains available on SQLite 3.37 and newer.

Call sqlite::initialize() on one startup thread after any native sqlite3_config
setup and before starting worker threads. Check its result. This controls startup
order; it does not establish a clean concurrent cold-start TSan result. See the
[TSan scope](../tests/CONCURRENCY.md) and [validation summary](validation.md).
