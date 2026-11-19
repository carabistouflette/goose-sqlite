#!/usr/bin/env python3
"""Assert the sanitizer negative control stops the injected generated-path fault."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import os
import subprocess

EXPECTED = 'AddressSanitizer: heap-buffer-overflow'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, help='the built negative control')
    parser.add_argument('--log', required=True, help='where to keep the raw output')
    args = parser.parse_args()

    environment = dict(os.environ)
    environment['ASAN_OPTIONS'] = 'detect_leaks=1'
    environment['UBSAN_OPTIONS'] = 'halt_on_error=1'
    completed = subprocess.run([args.binary], capture_output=True, text=True,
                               env=environment)
    output = completed.stdout + completed.stderr
    with open(args.log, 'w') as handle:
        handle.write(output)

    if completed.returncode == 0:
        parser.exit(1, 'negative control exited 0: the sanitizer did not stop the '
                       f'fault, so the generated path is not instrumented\n')
    if EXPECTED not in output:
        parser.exit(1, f'negative control did not report {EXPECTED!r}; '
                       f'see {args.log}\n')
    print(f'negative control stopped by {EXPECTED} (exit {completed.returncode})')


if __name__ == '__main__':
    main()
