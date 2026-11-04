# Platforms and build requirements

Tested platforms are Linux x86-64 and Linux ARM64 with GCC or Clang,
pthreads, libc development headers and a thread-safe system SQLite library.
Native Ubuntu 24.04 CI runs the pinned Goose compiler, public runner/native/import
tests, both native sanitizer suites, verified pinned-engine positive WAL checks,
fuzz checks and benchmark correctness smoke checks on both architectures.
Architecture-specific toolchain cache keys prevent cross-architecture reuse.
Other architectures, libc implementations, macOS and Windows are unverified.
The native adapter uses POSIX thread-local resource cleanup; Windows would need
a reviewed platform implementation and tests.

## Toolchain

- Git, Make, Python 3 and CMake 3.27+ for the pinned Goose compiler bootstrap.
- A C++20 compiler for Goose; a C11 compiler for this adapter.
- SQLite 3.37+ development headers and library, with extension configuration and
  thread-safety support. The application must not globally select SQLite's
  single-thread mode. SQLite is dynamically linked, not vendored.
- Clang with ASan/UBSan/libFuzzer for fuzz checks, and GCC/Clang sanitizer runtimes
  for their respective native test targets. Separate x86-64 TSan CI instruments
  both the verified engine and adapter; see its [initialization scope](../tests/CONCURRENCY.md).
- GCC by default for the optional benchmark harness; BENCH_CC may select another
  single compiler executable. Measurement tooling uses Linux ldd and process
  resource accounting.

`make setup` builds the exact full upstream commit in GOOSE_REVISION with optional
graphics/audio disabled. Existing compilers can be selected through GOOSE. The
in-process runner needs libc development headers; native builds need a working C
linker/toolchain. Source and native package caches are not shipped with the library.

## Engine and policy compatibility

The SQLite minimum is an interface requirement, not a recommendation to install
an old engine. Use your operating system's security-supported SQLite package.
Compile-time SQLite options can remove functionality or impose tighter limits;
the supported interface limits are in api.md. Connection security configuration
failures abort open rather than silently weakening policy.

The initial host uses SQLite 3.54.1, GCC 16.2.1 and Clang 23. Hosted CI uses
Ubuntu 24.04 and its packaged SQLite. Exact upstream 3.37.0 and Ubuntu noble-security 3.45.1-1ubuntu2.8 packages also
passed cross-engine checks on the initial Linux host. Exact completed checks,
configurations and CI evidence are recorded in [validation.md](validation.md).

Before starting workers, call sqlite::initialize on one startup thread after any
native SQLite configuration and check its result. This supports deterministic
startup and SQLITE_OMIT_AUTOINIT engines without changing ordinary open behavior.
Initialization failures remain retryable; no public shutdown API is provided.

Independent connections can execute on separate OS threads. Handles cannot move
between threads; each thread opens its own connection. No cross-process locking
or transaction guarantees beyond SQLite's own engine/filesystem behavior are added.

Optional WAL requires recognized SQLite versions containing the WAL-reset fix:
3.51.3+, 3.50.7..3.50.x, or 3.44.6..3.44.x. Other versions, including unrecognized
distributor backports, reject requested/detected WAL at open. Rollback-journal
operations remain available on 3.37+. All processes participating in WAL access
must use patched engines; open-time inspection cannot control external changes.
WAL needs one host and a suitable local filesystem, sidecars and permissions.
See [the complete storage contract](api.md) for limits and engine restrictions.

Public test executables can use separate output directories with
`make test PUBLIC_TEST_DIR=.build/public-host` (and a distinct GOOSE_HOME/native
prefix for each engine). This prevents concurrent compatibility runs from sharing
executable paths. The validated follow-up uses isolated directories and verifies
the actual loaded engine; overlapping exploratory runs are not counted.
