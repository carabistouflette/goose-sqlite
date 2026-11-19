#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Require generated-object instrumentation separately from runtime interception."""
import argparse
from pathlib import Path
import subprocess


def require_instrumentation(obj):
    text=subprocess.check_output(['nm','-u',str(obj)],text=True,timeout=30)
    if '__asan_' not in text or '__ubsan_' not in text:
        raise RuntimeError('generated object lacks ASan/UBSan compile-time instrumentation')
    return text


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--object',required=True)
    parser.add_argument('--binary',required=True)
    parser.add_argument('--log',required=True)
    args=parser.parse_args()
    symbols=require_instrumentation(args.object)
    with Path(args.log+'.symbols').open('x') as out:out.write(symbols)
    result=subprocess.run([args.binary],capture_output=True,text=True,timeout=30)
    text=result.stdout+result.stderr
    with Path(args.log).open('x') as out:out.write(text)
    if not result.returncode or 'AddressSanitizer: heap-buffer-overflow' not in text:
        parser.exit(1,'runtime control did not diagnose the memory fault\n')
    print('generated-object instrumentation and runtime memory diagnosis confirmed')


if __name__=='__main__':main()
