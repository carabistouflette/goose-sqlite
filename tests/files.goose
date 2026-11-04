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
    print("sqlite file API tests passed");
}
