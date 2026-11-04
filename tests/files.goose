// SPDX-License-Identifier: Apache-2.0
import sqlite from "..";
import std;
import os;

fn main() {
    let argv = args();
    assert(argv.len == 2); // Harness supplies a path in a private temp directory.
    var options = sqlite::Options { busy_ms: 1 };
    let db, opened = sqlite::open(argv[1], options);
    assert(opened == sqlite::OK);
    assert(sqlite::execute(db, "CREATE TABLE items(x INTEGER UNIQUE)") == sqlite::OK);
    assert(sqlite::execute(db, "INSERT INTO items VALUES(7)") == sqlite::OK);
    let other, other_opened = sqlite::open(argv[1], options);
    assert(other_opened == sqlite::OK);
    assert(sqlite::execute(db, "BEGIN IMMEDIATE") == sqlite::OK);
    assert(sqlite::execute(other, "INSERT INTO items VALUES(8)") == 5); // SQLITE_BUSY.
    assert(sqlite::execute(db, "ROLLBACK") == sqlite::OK);
    assert(sqlite::execute(other, "INSERT INTO items VALUES(8)") == sqlite::OK);
    let duplicate, duplicate_prepared = sqlite::prepare(other, "INSERT INTO items VALUES(7)");
    assert(duplicate_prepared == sqlite::OK);
    assert(sqlite::step(duplicate) == 2067);
    assert(sqlite::reset(duplicate) == 2067); // Previous error, but now Ready.
    assert(sqlite::step(duplicate) == 2067);
    assert(sqlite::finalize(duplicate) == 2067); // Destruction reports error too.
    assert(sqlite::step(duplicate) == sqlite::INVALID_HANDLE);
    let returning, returning_prepared = sqlite::prepare(other, "INSERT INTO items VALUES(9) RETURNING x");
    assert(returning_prepared == sqlite::OK && sqlite::step(returning) == sqlite::ROW);
    let value, read = sqlite::column_integer(returning, 0);
    assert(read == sqlite::OK && value == 9);
    assert(sqlite::step(returning) == sqlite::DONE);
    assert(sqlite::finalize(returning) == sqlite::OK);
    assert(sqlite::close(other) == sqlite::OK && sqlite::close(db) == sqlite::OK);
    options.readonly = true;
    let reopened, reopen_code = sqlite::open(argv[1], options);
    assert(reopen_code == sqlite::OK);
    let query, queried = sqlite::prepare(reopened, "SELECT sum(x) FROM items");
    assert(queried == sqlite::OK && sqlite::step(query) == sqlite::ROW);
    let total, summed = sqlite::column_integer(query, 0);
    assert(summed == sqlite::OK && total == 24);
    assert(sqlite::finalize(query) == sqlite::OK);
    let denied = sqlite::execute(reopened, "INSERT INTO items VALUES(10)");
    assert(denied > 0 && (denied & 255) == 8); // SQLITE_READONLY.
    assert(sqlite::close(reopened) == sqlite::OK);
    let missing_path = str(argv[1], "/missing/database.sqlite");
    for i in 20 {
        let missing, failed = sqlite::open(missing_path, options);
        assert(failed > 0 && missing.token == 0);
    }
    let recovered, recovered_code = sqlite::open(":memory:", options);
    assert(recovered_code == sqlite::OK && sqlite::close(recovered) == sqlite::OK);
    let wal_options = sqlite::Options { wal: true, busy_ms: 1 };
    let wal_path = str(argv[1], ".wal-test");
    let writer, wal_code = sqlite::open(wal_path, wal_options);
    if wal_code == 21 { assert(writer.token == 0); } // Old/unrecognized WAL engine: fail closed.
    else {
        assert(wal_code == sqlite::OK);
        assert(sqlite::execute(writer, "CREATE TABLE t(x)") == sqlite::OK);
        assert(sqlite::execute(writer, "INSERT INTO t VALUES(1)") == sqlite::OK);
        let read_options = sqlite::Options { .. };
        let reader, reader_code = sqlite::open(wal_path, read_options);
        assert(reader_code == sqlite::OK && sqlite::execute(reader, "BEGIN") == sqlite::OK);
        let snapshot, snapshot_code = sqlite::prepare(reader, "SELECT x FROM t");
        assert(snapshot_code == sqlite::OK && sqlite::step(snapshot) == sqlite::ROW);
        assert(sqlite::execute(writer, "UPDATE t SET x=2") == sqlite::OK);
        let old, old_code = sqlite::column_integer(snapshot, 0);
        assert(old_code == sqlite::OK && old == 1);
        assert(sqlite::finalize(snapshot) == sqlite::OK && sqlite::execute(reader, "COMMIT") == sqlite::OK);
        assert(sqlite::execute(writer, "PRAGMA journal_mode") == 23);
        assert(sqlite::close(reader) == sqlite::OK && sqlite::close(writer) == sqlite::OK);
    }
    print("sqlite file API tests passed");
}
