#!/usr/bin/env python3
"""Verify a local or pinned Git import from an isolated consumer and package cache."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--goose', required=True)
    parser.add_argument('--source', default=str(ROOT), help='Package path or owner/repo@full-commit')
    args = parser.parse_args()
    goose = str(Path(args.goose).resolve())
    with tempfile.TemporaryDirectory(prefix='goose-sqlite-import-') as tmp:
        consumer = Path(tmp)
        env = os.environ.copy()
        env['GOOSE_HOME'] = str(consumer / 'cache')
        program = '''import sqlite from SOURCE;
import std;

fn main() {
    let options = sqlite::Options { .. };
    let db, opened = sqlite::open(":memory:", options);
    assert(opened == sqlite::OK);
    let stmt, prepared = sqlite::prepare(db, "SELECT ?1, ?2");
    assert(prepared == sqlite::OK);
    assert(sqlite::bind_integer(stmt, 1, 42) == sqlite::OK);
    assert(sqlite::bind_text(stmt, 2, "Goose's bytes") == sqlite::OK);
    assert(sqlite::step(stmt) == sqlite::ROW);
    let value, read = sqlite::column_integer(stmt, 0);
    assert(read == sqlite::OK && value == 42);
    var bytes: u8[>..] = [];
    assert(sqlite::column_text(stmt, 1, bytes) == sqlite::OK);
    assert(bytes == "Goose's bytes");
    assert(sqlite::step(stmt) == sqlite::DONE);
    assert(sqlite::finalize(stmt) == sqlite::OK);
    assert(sqlite::close(db) == sqlite::OK);
    assert(bytes == "Goose's bytes");
    print("sqlite standalone import passed");
}
'''
        (consumer / 'main.goose').write_text(program.replace('SOURCE', json.dumps(args.source, ensure_ascii=False)))
        expected = 'sqlite standalone import passed'
        runner = subprocess.run([goose, 'run', 'main.goose'], cwd=consumer, env=env,
                                check=True, text=True, stdout=subprocess.PIPE)
        if runner.stdout.strip() != expected:
            raise RuntimeError(f'unexpected runner output: {runner.stdout!r}')
        subprocess.run([goose, 'build', 'main.goose', '-o', 'consumer'], cwd=consumer, env=env, check=True)
        native = subprocess.run([str(consumer / 'consumer')], cwd=consumer, env=env,
                                check=True, text=True, stdout=subprocess.PIPE)
        if native.stdout.strip() != expected:
            raise RuntimeError(f'unexpected native output: {native.stdout!r}')
        print(expected + ' (runner and native, isolated consumer/cache)')


if __name__ == '__main__':
    main()
