// SPDX-License-Identifier: Apache-2.0
import sqlite from "../..";
import std;
import os;

fn changed_one(db: sqlite::Database) {
    let count, code = sqlite::changes(db);
    assert(code == sqlite::OK && count == 1);
}
fn insert_one(db: sqlite::Database, stmt: sqlite::Statement, id: i64, payload: const u8[:]) {
    assert(sqlite::bind_integer(stmt, 1, id) == sqlite::OK);
    assert(sqlite::bind_blob(stmt, 2, payload) == sqlite::OK);
    assert(sqlite::step(stmt) == sqlite::DONE);
    changed_one(db);
    assert(sqlite::reset(stmt) == sqlite::OK);
}
fn verify(db: sqlite::Database, rows: i64, payload: const u8[:]) -> i64 {
    let query, prepared = sqlite::prepare(db, "SELECT id,payload FROM items ORDER BY id");
    assert(prepared == sqlite::OK);
    var out:      u8[>..] = []; out.resize(128, 0);
    var checksum: i64     = 0;
    for position in rows + 1 {
        assert(sqlite::step(query) == sqlite::ROW);
        let id, code = sqlite::column_integer(query, 0);
        assert(code == sqlite::OK && id == position - 1);
        assert(sqlite::column_blob(query, 1, out) == sqlite::OK && out == payload);
        checksum += id + 2;
    }
    assert(sqlite::step(query) == sqlite::DONE);
    assert(sqlite::finalize(query) == sqlite::OK);
    return checksum;
}
fn main() {
    let argv = args();
    assert(argv.len == 5);
    let mode = argv[2];
    assert(mode == "commit" || mode == "rollback" || mode == "busy");
    let transactions, valid_transactions = parse_int(argv[3]);
    let batch, valid_batch = parse_int(argv[4]);
    assert(valid_transactions && transactions >= 1 && transactions <= 10000);
    assert(valid_batch && batch >= 1 && batch <= 1024);
    assert(transactions * batch <= 1000000);
    var payload: u8[>..] = []; payload.resize(128, 'x');
    payload[0] = 0; payload[127] = 255;
    var latencies: i64[>..] = []; latencies.resize(transactions, 0);
    var codes:     i64[>..] = []; codes.resize(transactions, 0);
    let options = sqlite::Options { busy_ms: 0, work_budget: 100000000 };
    let db, opened = sqlite::open(argv[1], options);
    assert(opened == sqlite::OK);
    let insert, prepared = sqlite::prepare(db, "INSERT INTO items VALUES(?1,?2)");
    assert(prepared == sqlite::OK);

    // Prime the reused insert and each normal control-SQL path outside timing.
    assert(sqlite::execute(db, "BEGIN IMMEDIATE") == sqlite::OK);
    insert_one(db, insert, -2, payload);
    assert(sqlite::execute(db, "ROLLBACK") == sqlite::OK);
    assert(sqlite::execute(db, "BEGIN IMMEDIATE") == sqlite::OK);
    assert(sqlite::execute(db, "COMMIT") == sqlite::OK);
    assert(sqlite::execute(db, "BEGIN IMMEDIATE") == sqlite::OK);
    assert(sqlite::execute(db, "ROLLBACK") == sqlite::OK);

    var elapsed:       i64 = 0;
    var commits:       i64 = 0;
    var busy:          i64 = 0;
    var rollbacks:     i64 = 0;
    var expected_rows: i64 = 0;
    if mode == "busy" {
        let blocker, blocker_opened = sqlite::open(argv[1], options);
        assert(blocker_opened == sqlite::OK);
        assert(sqlite::execute(blocker, "BEGIN IMMEDIATE") == sqlite::OK);
        assert(sqlite::execute(blocker, "UPDATE items SET payload=zeroblob(128) WHERE id=-1") == sqlite::OK);
        changed_one(blocker);
        let loop_start = clock_ns();
        for transaction in transactions {
            let start = clock_ns();
            let code = sqlite::execute(db, "BEGIN IMMEDIATE");
            assert(code > 0 && code % 256 == 5);
            let automatic, automatic_code = sqlite::autocommit(db);
            assert(automatic_code == sqlite::OK && automatic);
            latencies[transaction] = clock_ns() - start;
            codes[transaction] = code;
        }
        elapsed = clock_ns() - loop_start;
        busy = transactions;
        assert(sqlite::execute(blocker, "ROLLBACK") == sqlite::OK);
        assert(sqlite::close(blocker) == sqlite::OK);
        // Recovery uses the same primary connection and is outside both clocks.
        assert(sqlite::execute(db, "BEGIN IMMEDIATE") == sqlite::OK);
        insert_one(db, insert, 0, payload);
        assert(sqlite::execute(db, "COMMIT") == sqlite::OK);
        expected_rows = 1;
    } else {
        let finish = if mode == "commit" { "COMMIT" } else { "ROLLBACK" };
        let loop_start = clock_ns();
        for transaction in transactions {
            let start = clock_ns();
            assert(sqlite::execute(db, "BEGIN IMMEDIATE") == sqlite::OK);
            for row in batch { insert_one(db, insert, transaction * batch + row, payload); }
            assert(sqlite::execute(db, finish) == sqlite::OK);
            latencies[transaction] = clock_ns() - start;
        }
        elapsed = clock_ns() - loop_start;
        if mode == "commit" { commits = transactions; expected_rows = transactions * batch; }
        else { rollbacks = transactions; }
    }
    assert(elapsed > 0);
    for latency in latencies { assert(latency > 0); }
    assert(sqlite::finalize(insert) == sqlite::OK);
    let checksum = verify(db, expected_rows, payload);
    assert(checksum == 1 + expected_rows * (expected_rows + 3) / 2);
    assert(sqlite::close(db) == sqlite::OK);
    print("policy inferred");
    print(str(elapsed, " ", checksum, " ", commits, " ", busy, " ", rollbacks));
    for transaction in transactions { print(str(latencies[transaction], " ", codes[transaction])); }
}
