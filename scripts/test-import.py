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
    assert(sqlite::initialize() == sqlite::OK);
    assert(sqlite::initialize() == sqlite::OK);
    let options = sqlite::Options { .. };
    let db, opened = sqlite::open(":memory:", options);
    assert(opened == sqlite::OK);
    let log, checkpointed, checkpoint_code = sqlite::checkpoint(db, sqlite::CHECKPOINT_PASSIVE);
    assert((checkpoint_code == sqlite::OK || checkpoint_code == 21) && log == -1 && checkpointed == -1);
    let stmt, prepared = sqlite::prepare(db, "SELECT :number AS id, :label AS label");
    assert(prepared == sqlite::OK);
    assert(sqlite::parameter_count(stmt) == 2);
    let runs, runs_code = sqlite::statement_status(stmt, sqlite::STMT_RUNS, false);
    assert(runs_code == sqlite::OK && runs == 0);
    assert(sqlite::parameter_index(stmt, ":number") == 1);
    assert(sqlite::parameter_index(stmt, ":label") == 2);
    var column: u8[>..] = [];
    assert(sqlite::column_name(stmt, 1, column) == sqlite::OK && column == "label");
    let auto, auto_code = sqlite::autocommit(db);
    let changed, changed_code = sqlite::changes(db);
    let rowid, rowid_code = sqlite::last_insert_rowid(db);
    assert(auto_code == sqlite::OK && auto);
    assert(changed_code == sqlite::OK && changed == 0);
    assert(rowid_code == sqlite::OK && rowid == 0);
    assert(sqlite::bind_integer(stmt, 1, 42) == sqlite::OK);
    assert(sqlite::bind_text(stmt, 2, "Goose's bytes") == sqlite::OK);
    assert(sqlite::step(stmt) == sqlite::ROW);
    assert(sqlite::initialize() == sqlite::OK);
    let value, read = sqlite::column_integer(stmt, 0);
    assert(read == sqlite::OK && value == 42);
    var bytes: u8[>..] = [];
    assert(sqlite::column_text(stmt, 1, bytes) == sqlite::OK);
    assert(bytes == "Goose's bytes");
    assert(sqlite::step(stmt) == sqlite::DONE);
    assert(sqlite::finalize(stmt) == sqlite::OK);
    assert(sqlite::execute(db, "CREATE TABLE t(x)") == sqlite::OK);
    assert(sqlite::execute(db, "INSERT INTO t VALUES(zeroblob(32))") == sqlite::OK);
    assert(sqlite::execute(db, "BEGIN") == sqlite::OK);
    let blob, blob_code = sqlite::blob_open(db, "t", "x", 1, true);
    assert(blob_code == sqlite::OK && sqlite::blob_write(blob, 7, "safe") == sqlite::OK);
    let size, size_code = sqlite::blob_size(blob);
    assert(size_code == sqlite::OK && size == 32);
    assert(sqlite::blob_close(blob) == sqlite::OK && sqlite::execute(db, "COMMIT") == sqlite::OK);
    let destination, dst_code = sqlite::open(":memory:", options);
    assert(dst_code == sqlite::OK && sqlite::backup(db, destination, 100) == sqlite::OK);
    let copied, copied_code = sqlite::blob_open(destination, "t", "x", 1, false);
    assert(copied_code == sqlite::OK);
    var part: u8[>..] = [];
    assert(sqlite::blob_read(copied, 7, 4, part) == sqlite::OK && part == "safe");
    assert(sqlite::blob_close(copied) == sqlite::OK && sqlite::close(destination) == sqlite::OK);
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
