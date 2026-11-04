# Platforms and build requirements

The initial supported/tested platform is Linux x86-64 with GCC or Clang,
pthreads, libc development headers and a thread-safe system SQLite library.
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
  for their respective native test targets.
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
Ubuntu 24.04 and its packaged SQLite. Exact completed compatibility checks and
CI evidence are recorded in validation.md.

Independent connections can execute on separate OS threads. Handles cannot move
between threads; each thread opens its own connection. No cross-process locking
or transaction guarantees beyond SQLite's own engine/filesystem behavior are added.
