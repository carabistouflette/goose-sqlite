#!/usr/bin/env python3
"""Validate positive WAL behavior with a pinned, instrumented SQLite engine."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
URL = 'https://sqlite.org/2026/sqlite-amalgamation-3540100.zip'
ARCHIVE_SHA256 = '0a9c8e34352dad46006aa82836d5383bff9dc6bc9ce5a60553c05aa30e6ad1f9'
# First-party release record: https://sqlite.org/releaselog/3_54_1.html
SOURCE_SHA3 = 'e2b869d3003b33c942b7dd7063604fbc53553e1b66609570df39b9b7b558ee81'


def run(cmd, env=None, capture=False):
    return subprocess.run([str(x) for x in cmd], cwd=ROOT, env=env, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='clang')
    args = parser.parse_args()
    build = ROOT / '.build/wal-engine'
    include = build / 'include'; include.mkdir(parents=True, exist_ok=True)
    lib = build / 'lib'; lib.mkdir(exist_ok=True)
    with urllib.request.urlopen(URL, timeout=60) as response:
        archive = response.read(8 * 1024 * 1024 + 1)
    if len(archive) > 8 * 1024 * 1024 or hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError('Pinned SQLite archive verification failed')
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        source = zipped.read('sqlite-amalgamation-3540100/sqlite3.c')
        header = zipped.read('sqlite-amalgamation-3540100/sqlite3.h')
    if hashlib.sha3_256(source).hexdigest() != SOURCE_SHA3:
        raise RuntimeError('Upstream SQLite source verification failed')
    (build / 'sqlite3.c').write_bytes(source); (include / 'sqlite3.h').write_bytes(header)
    env = os.environ.copy()
    for key in ('CFLAGS','CXXFLAGS','CPPFLAGS','LDFLAGS','CMAKE_GENERATOR','CMAKE_TOOLCHAIN_FILE','CMAKE_PREFIX_PATH'):
        env.pop(key, None)
    flags = ['-O1','-g','-fno-omit-frame-pointer','-fsanitize=address,undefined']
    engine = lib / 'libsqlite3.so.0'
    run([args.cc,*flags,'-std=c11','-shared','-fPIC','-DSQLITE_THREADSAFE=1',
         '-DSQLITE_DEFAULT_WAL_SYNCHRONOUS=1',build / 'sqlite3.c','-Wl,-soname,libsqlite3.so.0',
         '-o',engine,'-lpthread','-ldl','-lm'], env)
    link = lib / 'libsqlite3.so'
    if link.is_symlink(): link.unlink()
    link.symlink_to(engine.name)
    native = build / 'native'
    run(['cmake','-S','.', '-B',native,f'-DCMAKE_C_COMPILER={args.cc}','-DCMAKE_BUILD_TYPE=Debug',
         '-DGOOSE_SQLITE_NATIVE_TESTS=ON',f'-DSQLite3_INCLUDE_DIR={include}',f'-DSQLite3_LIBRARY={link}'],env)
    run(['cmake','--build',native,'--parallel','2'],env)
    env['LD_LIBRARY_PATH'] = str(lib) + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    env['UBSAN_OPTIONS'] = 'halt_on_error=1'
    linkage = run(['ldd',native / 'goose_sqlite_storage_test'],env,capture=True).stdout
    if str(lib) not in linkage: raise RuntimeError('Test did not load pinned engine')
    for name in ('goose_sqlite_test','goose_sqlite_fault_test','goose_sqlite_storage_test'):
        run([native / name],env)
    run(['python3','scripts/test-recovery.py','--binary',native / 'goose_sqlite_recovery_test','--output',build / 'recovery.json'],env)
    evidence = dict(url=URL, archive_sha256=ARCHIVE_SHA256, sqlite3_c_sha3_256=SOURCE_SHA3,
                    engine_sha256=hashlib.sha256(engine.read_bytes()).hexdigest(),
                    compiler=run([args.cc,'--version'],capture=True).stdout.splitlines()[0],
                    flags=flags+['-std=c11','-shared','-fPIC','SQLITE_THREADSAFE=1','SQLITE_DEFAULT_WAL_SYNCHRONOUS=1'],
                    tests='native, allocation failures, storage incl FULL/EXTRA and backup mismatch; engine+adapter ASan/UBSan')
    (build / 'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print('Pinned SQLite WAL engine and adapter sanitizer tests passed')


if __name__ == '__main__':
    main()
