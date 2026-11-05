#!/usr/bin/env python3
"""Validate positive WAL behavior with a pinned, instrumented SQLite engine."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
URL = 'https://sqlite.org/2026/sqlite-amalgamation-3540100.zip'
ARCHIVE_SHA256 = '0a9c8e34352dad46006aa82836d5383bff9dc6bc9ce5a60553c05aa30e6ad1f9'
# First-party release record: https://sqlite.org/releaselog/3_54_1.html
SOURCE_SHA3 = 'e2b869d3003b33c942b7dd7063604fbc53553e1b66609570df39b9b7b558ee81'


def run(cmd, env=None, capture=False, timeout=300):
    return subprocess.run([str(x) for x in cmd], cwd=ROOT, env=env, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--sanitizer', choices=('address', 'thread'), default='address')
    args = parser.parse_args()
    thread = args.sanitizer == 'thread'
    build = ROOT / ('.build/tsan-engine' if thread else '.build/wal-engine')
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
    flags = ['-O1','-g','-fno-omit-frame-pointer',
             '-fsanitize=thread' if thread else '-fsanitize=address,undefined']
    env['UBSAN_OPTIONS'] = 'halt_on_error=1'
    env['TSAN_OPTIONS'] = 'halt_on_error=1:exitcode=66'
    if thread:
        probe = build / 'tsan-probe'
        run([args.cc,*flags,'-std=c11','-UNDEBUG','tests/tsan-probe.c','-pthread','-o',probe],env)
        result = subprocess.run([str(probe)],cwd=ROOT,env=env,text=True,capture_output=True,timeout=30)
        (build / 'probe.log').write_text(result.stdout + result.stderr)
        if result.returncode != 66 or 'WARNING: ThreadSanitizer: data race' not in result.stderr:
            raise RuntimeError('TSan did not detect the intentional probe race; runtime unsupported or broken')
    engine = lib / 'libsqlite3.so.0'
    run([args.cc,*flags,'-std=c11','-shared','-fPIC','-DSQLITE_THREADSAFE=1',
         '-DSQLITE_DEFAULT_WAL_SYNCHRONOUS=1',build / 'sqlite3.c','-Wl,-soname,libsqlite3.so.0',
         '-o',engine,'-lpthread','-ldl','-lm'], env)
    link = lib / 'libsqlite3.so'
    if link.is_symlink(): link.unlink()
    link.symlink_to(engine.name)
    native = build / 'native'
    run(['cmake','-S','.', '-B',native,f'-DCMAKE_C_COMPILER={args.cc}','-DCMAKE_BUILD_TYPE=Debug',
         f'-DGOOSE_SQLITE_NATIVE_TESTS={"OFF" if thread else "ON"}',
         f'-DGOOSE_SQLITE_TSAN={"ON" if thread else "OFF"}',
         f'-DSQLite3_INCLUDE_DIR={include}',f'-DSQLite3_LIBRARY={link}'],env)
    run(['cmake','--build',native,'--parallel','2'],env)
    env['LD_LIBRARY_PATH'] = str(lib) + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    linkage = run(['ldd',native / 'goose_sqlite_thread_test'],env,capture=True).stdout
    if str(lib) not in linkage: raise RuntimeError('Test did not load pinned engine')
    run(['python3','scripts/test-threads.py','--binary',native / 'goose_sqlite_thread_test',
         '--output',build / 'threads.json','--require-wal',
         *(['--initialize-engine'] if thread else [])],env)
    run([native / 'goose_sqlite_checkpoint_test','--require-wal'],env)
    run([native / 'goose_sqlite_zeroblob_test'],env)
    if not thread:
        for name in ('goose_sqlite_test','goose_sqlite_fault_test','goose_sqlite_storage_test'):
            run([native / name],env)
        run(['python3','scripts/test-recovery.py','--binary',native / 'goose_sqlite_recovery_test','--output',build / 'recovery.json','--require-wal'],env,timeout=3600)
    evidence = dict(url=URL, archive_sha256=ARCHIVE_SHA256, sqlite3_c_sha3_256=SOURCE_SHA3,
                    engine_sha256=hashlib.sha256(engine.read_bytes()).hexdigest(),
                    compiler=run([args.cc,'--version'],capture=True).stdout.splitlines()[0],
                    architecture=platform.machine(), sanitizer=args.sanitizer,
                    source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                    source_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
                    source_hashes={p:hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                   for p in ('scripts/test-wal-engine.py','tests/tsan-probe.c',
                                             'tests/checkpoint.c','tests/zeroblob.c','tests/faults.c',
                                             'native/sqlite.c','native/sqlite.h','CMakeLists.txt')},
                    flags=flags+['-std=c11','-shared','-fPIC','SQLITE_THREADSAFE=1','SQLITE_DEFAULT_WAL_SYNCHRONOUS=1'],
                    tests=('intentional-race preflight then required positive-WAL thread/checkpoint contention and zeroblob tests; engine+adapter TSan'
                           if thread else 'native, retryable initialization/allocation and BLOB materialization failures, storage/zeroblob, required positive-WAL threads/checkpoints and I/O/crash recovery; engine+adapter ASan/UBSan'))
    (build / 'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print('Pinned SQLite WAL engine and adapter sanitizer tests passed')


if __name__ == '__main__':
    main()
