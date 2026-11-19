#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# The --cc for the negative control: the sanitizer flags of
# scripts/sanitizer-cc.sh plus the fixture that hands the generated program an
# undersized heap buffer.
set -euo pipefail
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
link=("$script_dir/sanitize_fault.c" -no-pie)
for argument in "$@"; do
    case "$argument" in -c|-S|-E|--version) link=();; esac
done
exec "${SANITIZER_CC:-gcc}" "$@" -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined "${link[@]}"
