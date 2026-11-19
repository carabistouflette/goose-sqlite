#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# The C compiler `make sanitize` hands Goose as --cc, so the generated program,
# the runtime and the package's native adapter are all built with ASan and
# UBSan. SANITIZER_CC picks the compiler under test (gcc or clang).
set -euo pipefail
sanitizer_link=(-no-pie)
for argument in "$@"; do
    case "$argument" in -c|-S|-E|--version) sanitizer_link=();; esac
done
exec "${SANITIZER_CC:-gcc}" "$@" -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined "${sanitizer_link[@]}"
