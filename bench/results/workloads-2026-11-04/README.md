# Realistic workloads and registry measurements

This directory retains the complete pre-optimization350-sample five-caller series,
a seven-pair/ten-fixture140-sample native Goose comparison, instruction profiling,
and the validated GNU time RSS launcher probe. Final refreshed alternatives are
added after the safety checks. No samples are discarded for showing a regression.

The matched registry experiment preserves compiler profiles, runner sources,
SQLite engine hash, token/thread checks, copied ownership and key-owned cleanup.
Its raw scope is native executables; dynamically loaded TLS has different code
generation and is covered by correctness tests without a timing claim. All
measurement windows use a shared host and nonexclusive CPU7. Do not compare
absolute times across windows as a controlled speedup.

Profile paths are redacted to $REPO only; hashes and commands identify the original
and retained data. The RSS probe retains source and tool/interpreter/binary hashes.
GNU time measures whole benchmark-child lifetime, including startup, setup and
streaming verification and a small native launch footprint. It does not measure
incremental allocator use or SQLite heap alone. The C API caller uses a C++ driver.
