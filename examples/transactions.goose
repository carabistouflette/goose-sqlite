// SPDX-License-Identifier: Apache-2.0
import sqlite from "..";
import std;

// Keep the original operation error separate from a recovery/cleanup error.
struct Outcome { code: i64 = 0, recovery: i64 = 0 }
fn insert(db: sqlite::Database, value: i64, rollback_all: bool) -> i64 {
    let sql = if rollback_all { "INSERT OR ROLLBACK INTO items VALUES(?1)" }
        else { "INSERT INTO items VALUES(?1)" };
    let stmt, prepared = sqlite::prepare(db, sql);
    if prepared != sqlite::OK { return prepared; }
    var code = sqlite::bind_integer(stmt, 1, value);
    if code == sqlite::OK {
        code = sqlite::step(stmt);
        if code == sqlite::DONE { code = sqlite::OK; }
    }
    let cleanup = sqlite::finalize(stmt);
    return if code == sqlite::OK { cleanup } else { code };
}
fn recover(db: sqlite::Database, original: i64, savepoint: bool) -> Outcome {
    let auto, queried = sqlite::autocommit(db);
    if queried != sqlite::OK { return Outcome { code: original, recovery: queried }; }
    // INSERT OR ROLLBACK can already have ended the transaction/savepoint.
    if auto { return Outcome { code: original }; }
    var cleanup = sqlite::execute(db, if savepoint { "ROLLBACK TO example_scope" } else { "ROLLBACK" });
    if savepoint && cleanup == sqlite::OK { cleanup = sqlite::execute(db, "RELEASE example_scope"); }
    return Outcome { code: original, recovery: cleanup };
}
fn own_transaction(db: sqlite::Database, value: i64) -> Outcome {
    let begin = sqlite::execute(db, "BEGIN IMMEDIATE");
    // A failed BEGIN does not grant ownership of a caller's existing transaction.
    if begin != sqlite::OK { return Outcome { code: begin }; }
    let operation = insert(db, value, false);
    if operation != sqlite::OK { return recover(db, operation, false); }
    let committed = sqlite::execute(db, "COMMIT");
    if committed != sqlite::OK { return recover(db, committed, false); }
    return Outcome { .. };
}
fn nested_insert(db: sqlite::Database, value: i64, rollback_all: bool) -> Outcome {
    let auto, queried = sqlite::autocommit(db);
    if queried != sqlite::OK { return Outcome { code: queried }; }
    if auto { return Outcome { code: sqlite::INVALID_STATE }; }
    // Names and SQL here are fixed trusted code; values use typed bindings.
    let opened = sqlite::execute(db, "SAVEPOINT example_scope");
    if opened != sqlite::OK { return Outcome { code: opened }; }
    let operation = insert(db, value, rollback_all);
    if operation != sqlite::OK { return recover(db, operation, true); }
    let released = sqlite::execute(db, "RELEASE example_scope");
    if released != sqlite::OK { return recover(db, released, true); }
    return Outcome { .. }; // An inner RELEASE has not committed the outer transaction.
}
fn main() {
    let options = sqlite::Options { .. };
    let db, opened = sqlite::open(":memory:", options);
    assert(opened == sqlite::OK && sqlite::execute(db, "CREATE TABLE items(id INTEGER UNIQUE)") == sqlite::OK);
    let first = own_transaction(db, 1); assert(first.code == sqlite::OK && first.recovery == sqlite::OK);
    let duplicate = own_transaction(db, 1); assert(duplicate.code == 2067 && duplicate.recovery == sqlite::OK);
    assert(sqlite::execute(db, "BEGIN") == sqlite::OK);
    let unowned = own_transaction(db, 9); assert(unowned.code > 0 && unowned.recovery == sqlite::OK);
    let remains, remains_code = sqlite::autocommit(db); assert(remains_code == sqlite::OK && !remains);
    let inner = nested_insert(db, 1, false); assert(inner.code == 2067 && inner.recovery == sqlite::OK);
    let accepted = nested_insert(db, 2, false); assert(accepted.code == sqlite::OK && accepted.recovery == sqlite::OK);
    let still_open, still_code = sqlite::autocommit(db); assert(still_code == sqlite::OK && !still_open);
    let rolled = nested_insert(db, 1, true); assert(rolled.code == 2067 && rolled.recovery == sqlite::OK);
    let ended, ended_code = sqlite::autocommit(db); assert(ended_code == sqlite::OK && ended);
    let query, prepared = sqlite::prepare(db, "SELECT count(*),sum(id) FROM items");
    assert(prepared == sqlite::OK && sqlite::step(query) == sqlite::ROW);
    let count, counted = sqlite::column_integer(query, 0);
    let sum, summed = sqlite::column_integer(query, 1);
    assert(counted == sqlite::OK && count == 1 && summed == sqlite::OK && sum == 1);
    assert(sqlite::finalize(query) == sqlite::OK && sqlite::close(db) == sqlite::OK);
    print("sqlite transaction recovery example passed");
}
