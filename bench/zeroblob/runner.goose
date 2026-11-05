// SPDX-License-Identifier: Apache-2.0
import sqlite from "../..";
import std;
import os;

fn checked_row(stmt: sqlite::Statement, mode: i64, size: i64, input: const u8[:], out: u8[>..]&) {
    let bound = if mode == 0 { sqlite::bind_blob(stmt, 1, input) }
        else if mode == 1 { sqlite::bind_zeroblob(stmt, 1, size) }
        else { sqlite::bind_integer(stmt, 1, size) };
    assert(bound == sqlite::OK && sqlite::step(stmt) == sqlite::ROW);
    // column_blob itself requires BLOB storage and returns an owned copy.
    assert(sqlite::column_blob(stmt, 0, out) == sqlite::OK && out.len == size);
    for byte in out { assert(byte == 0); }
    assert(sqlite::step(stmt) == sqlite::DONE && sqlite::reset(stmt) == sqlite::OK);
}
fn main() {
    let argv = args(); assert(argv.len == 4);
    let iterations, valid = parse_int(argv[1]);
    let size, valid_size = parse_int(argv[3]);
    assert(valid && iterations > 0 && iterations <= 10000000);
    assert(valid_size && size >= 0 && size <= 1048576);
    assert(argv[2] == "copy" || argv[2] == "zero" || argv[2] == "sql");
    let mode: i64 = if argv[2] == "copy" { 0 } else if argv[2] == "zero" { 1 } else { 2 };
    assert(sqlite::initialize() == sqlite::OK);
    let options = sqlite::Options { .. };
    let db, opened = sqlite::open(":memory:", options); assert(opened == sqlite::OK);
    let query, prepared = sqlite::prepare(db, if mode == 2 { "SELECT zeroblob(?1)" } else { "SELECT ?1" });
    assert(prepared == sqlite::OK);
    var input: u8[>..] = []; if mode == 0 { input.resize(size, 0); }
    var out:   u8[>..] = []; out.resize(size, 0);
    checked_row(query, mode, size, input, out); // Prime the same statement before timing.
    var checksum: i64 = 0;
    let start = clock_ns();
    for i in iterations {
        checked_row(query, mode, size, input, out);
        checksum += out.len + 1;
    }
    let elapsed = clock_ns() - start;
    assert(sqlite::finalize(query) == sqlite::OK && sqlite::close(db) == sqlite::OK);
    print(elapsed, " ", checksum);
}
