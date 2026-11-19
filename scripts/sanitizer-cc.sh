#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
compiler=${SANITIZER_CC:-gcc}
# The supported Linux sanitizer profile is non-PIE: this avoids the observed
# GCC16 libubsan/PIE linkage failure. Production binaries are unaffected.
# -UNDEBUG also overrides CMake Release's -DNDEBUG in the native adapter.
probe=false
link=(-no-pie)
for argument in "$@"; do
    case "$argument" in
      --version|-v|-dumpversion|-dumpmachine) probe=true ;;
      -c|-S|-E) link=() ;;
    esac
done
if "$probe"; then exec "$compiler" "$@"; fi
effective=("$compiler" "$@" -O1 -g -UNDEBUG -fno-omit-frame-pointer -fsanitize=address,undefined "${link[@]}")
if [[ -n ${SANITIZER_COMMAND_LOG:-} ]]; then
    python3 - "${effective[@]}" <<'PY'
import json,os,sys
with open(os.environ['SANITIZER_COMMAND_LOG'],'a') as log:
    log.write(json.dumps({'cwd':os.getcwd(),'command':sys.argv[1:]})+'\n')
PY
fi
exec "${effective[@]}"
