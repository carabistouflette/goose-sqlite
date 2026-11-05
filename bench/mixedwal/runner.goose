// SPDX-License-Identifier: Apache-2.0
import sqlite from "../..";
import std;
import os;

fn checked(code: i64, stage: const u8[:]) {
    if code != sqlite::OK { abort(str(stage, " code=", code)); }
}
fn control(db: sqlite::Database, sql: const u8[:]) {
    checked(sqlite::execute(db, sql), sql);
}
fn automatic(db: sqlite::Database) {
    let enabled, code = sqlite::autocommit(db);
    checked(code, "autocommit");
    assert(enabled);
}
fn emit(line: const u8[:]) {
    write_stdout(line);
    write_stdout("\n");
    flush_stdout();
}
fn receive(command: u8[>..]&) {
    command.clear();
    if !read_line(command) { abort("unexpected command EOF"); }
    assert(command.len == 1);
}
fn update_all(db: sqlite::Database, query: sqlite::Statement, rows: i64,
              epoch: i64, expected: const u8[:]) {
    for id in rows {
        let offset = (epoch * rows + id) * 128;
        checked(sqlite::bind_integer(query, 1, epoch), "bind epoch");
        checked(sqlite::bind_blob(query, 2, expected[offset..offset + 128]), "bind payload");
        checked(sqlite::bind_integer(query, 3, id), "bind id");
        let code = sqlite::step(query);
        if code != sqlite::DONE { abort(str("update step code=", code)); }
        let count, changed = sqlite::changes(db);
        checked(changed, "changes");
        assert(count == 1);
        checked(sqlite::reset(query), "update reset");
    }
}
fn snapshot(query: sqlite::Statement, rows: i64, attempts: i64,
            expected: const u8[:], out: u8[>..]&) -> i64 {
    var epoch: i64 = -1;
    for id in rows {
        let stepped = sqlite::step(query);
        if stepped != sqlite::ROW { abort(str("snapshot step code=", stepped)); }
        let actual, actual_code = sqlite::column_integer(query, 0);
        let generation, epoch_code = sqlite::column_integer(query, 1);
        checked(actual_code, "snapshot id");
        checked(epoch_code, "snapshot epoch");
        assert(actual == id && generation >= 0 && generation <= attempts);
        if id == 0 { epoch = generation; }
        assert(generation == epoch);
        checked(sqlite::column_blob(query, 2, out), "snapshot payload");
        let offset = (epoch * rows + id) * 128;
        assert(out == expected[offset..offset + 128]);
    }
    let finished = sqlite::step(query);
    if finished != sqlite::DONE { abort(str("snapshot done code=", finished)); }
    checked(sqlite::reset(query), "snapshot reset");
    return epoch;
}
fn main() {
    let argv = args();
    assert(argv.len == 7);
    let role = argv[2];
    let phase = argv[3];
    assert(role == "reader" || role == "writer");
    assert(phase == "qualify" || phase == "mixed");
    let attempts, valid_attempts = parse_int(argv[4]);
    let rows, valid_rows = parse_int(argv[5]);
    let read_cap, valid_cap = parse_int(argv[6]);
    assert(valid_attempts && attempts >= 8 && attempts <= 4096);
    assert(valid_rows && rows >= 1 && rows <= 256);
    assert(valid_cap && read_cap >= 1 && read_cap <= 100000);
    assert((attempts + 1) * rows <= 32768);
    var expected: u8[>..] = [];
    expected.resize((attempts + 1) * rows * 128, 0);
    for epoch in attempts + 1 {
        for id in rows {
            let offset = (epoch * rows + id) * 128;
            for byte in 128 {
                expected[offset + byte] = ((epoch * 17 + id * 31 + byte * 7) % 256) as! u8;
            }
            expected[offset] = 0;
            expected[offset + 127] = 255;
        }
    }
    let options = sqlite::Options { busy_ms: 0, work_budget: 100000000 };
    let db, opened = sqlite::open(argv[1], options);
    checked(opened, "open");
    let query, prepared = sqlite::prepare(db, if role == "reader" {
        "SELECT id,epoch,payload FROM items ORDER BY id"
    } else { "UPDATE items SET epoch=?1,payload=?2 WHERE id=?3" });
    checked(prepared, "prepare");
    var out: u8[>..] = []; out.resize(128, 0);
    if role == "reader" {
        control(db, "BEGIN DEFERRED");
        assert(snapshot(query, rows, attempts, expected, out) == 0);
        control(db, "COMMIT");
    }
    else {
        control(db, "BEGIN IMMEDIATE");
        update_all(db, query, rows, 0, expected);
        control(db, "ROLLBACK");
        control(db, "BEGIN IMMEDIATE");
        control(db, "COMMIT");
        control(db, "BEGIN IMMEDIATE");
        control(db, "ROLLBACK");
    }
    automatic(db);
    emit("policy inferred");
    emit(str("READY ", role));
    var command: u8[>..] = [];
    if phase == "qualify" {
        var step: i64 = 0;
        while true {
            receive(command);
            if role == "writer" {
                if step == 0 {
                    assert(command == "C");
                    control(db, "BEGIN IMMEDIATE");
                    update_all(db, query, rows, 1, expected);
                    control(db, "COMMIT");
                    emit("COMMITTED 1");
                } else if step == 1 {
                    assert(command == "U");
                    control(db, "BEGIN IMMEDIATE");
                    update_all(db, query, rows, 2, expected);
                    emit("DIRTY 2");
                } else if step == 2 {
                    assert(command == "B");
                    control(db, "ROLLBACK");
                    emit("ROLLED_BACK 2");
                } else { assert(step == 3 && command == "S"); break; }
            } else {
                if step == 0 {
                    assert(command == "H");
                    control(db, "BEGIN DEFERRED");
                    assert(snapshot(query, rows, attempts, expected, out) == 0);
                    emit("HELD 0");
                } else if step == 1 {
                    assert(command == "V");
                    assert(snapshot(query, rows, attempts, expected, out) == 0);
                    emit("VERIFIED 0");
                } else if step >= 2 && step <= 4 {
                    assert(command == "F");
                    if step == 2 { control(db, "COMMIT"); }
                    control(db, "BEGIN DEFERRED");
                    assert(snapshot(query, rows, attempts, expected, out) == 1);
                    control(db, "COMMIT");
                    emit("FRESH 1");
                } else { assert(step == 5 && command == "S"); break; }
            }
            step += 1;
        }
    } else {
        receive(command);
        assert(command == "G");
        emit(str("START ", role));
        if role == "writer" {
            var commits: i64 = 0;
            var busy:    i64 = 0;
            let loop_start = clock_ns();
            for attempt in attempts {
                let start = clock_ns();
                let code = sqlite::execute(db, "BEGIN IMMEDIATE");
                if code > 0 && code % 256 == 5 { automatic(db); busy += 1; }
                else {
                    checked(code, "writer begin");
                    update_all(db, query, rows, commits + 1, expected);
                    control(db, "COMMIT");
                    commits += 1;
                }
                let elapsed = clock_ns() - start;
                assert(elapsed > 0);
                emit(str("W ", attempt + 1, " ", elapsed, " ", code, " ", commits));
            }
            let elapsed = clock_ns() - loop_start;
            assert(elapsed > 0);
            emit(str("DONE writer ", elapsed, " ", commits, " ", busy));
        } else {
            var reads:    i64 = 0;
            var busy:     i64 = 0;
            var count:    i64 = 0;
            var previous: i64 = 0;
            let loop_start = clock_ns();
            while true {
                assert(count < read_cap);
                let start = clock_ns();
                let code = sqlite::execute(db, "BEGIN DEFERRED");
                var epoch: i64 = -1;
                if code > 0 && code % 256 == 5 { automatic(db); busy += 1; }
                else {
                    checked(code, "reader begin");
                    epoch = snapshot(query, rows, attempts, expected, out);
                    assert(epoch >= previous);
                    previous = epoch;
                    control(db, "COMMIT");
                    reads += 1;
                }
                let elapsed = clock_ns() - start;
                assert(elapsed > 0);
                count += 1;
                emit(str("R ", count, " ", elapsed, " ", code, " ", epoch));
                receive(command);
                if command == "S" { break; }
                assert(command == "N");
            }
            let elapsed = clock_ns() - loop_start;
            assert(elapsed > 0);
            emit(str("DONE reader ", elapsed, " ", reads, " ", busy));
        }
    }
    automatic(db);
    checked(sqlite::finalize(query), "finalize");
    checked(sqlite::close(db), "close");
    emit(str("END ", role));
}
