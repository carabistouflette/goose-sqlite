// SPDX-License-Identifier: Apache-2.0
import sqlite from "..";
import std;

fn zeros(query: sqlite::Statement, size: i64) {
    assert(sqlite::step(query) == sqlite::ROW && sqlite::column_type(query, 0) == sqlite::BLOB);
    var out: u8[>..] = []; out.append("old bytes");
    assert(sqlite::column_blob(query, 0, out) == sqlite::OK && out.len == size);
    for byte in out { assert(byte == 0); }
    assert(sqlite::bind_zeroblob(query, 1, size) == sqlite::INVALID_STATE);
    assert(sqlite::step(query) == sqlite::DONE);
    assert(sqlite::bind_zeroblob(query, 1, size) == sqlite::INVALID_STATE);
    assert(sqlite::reset(query) == sqlite::OK);
}
fn integer(query: sqlite::Statement, expected: i64) {
    assert(sqlite::step(query) == sqlite::ROW);
    let value, code = sqlite::column_integer(query, 0);
    assert(code == sqlite::OK && value == expected);
    assert(sqlite::step(query) == sqlite::DONE && sqlite::reset(query) == sqlite::OK);
}
fn main() {
    assert(sqlite::initialize() == sqlite::OK);
    let options = sqlite::Options { .. };
    let db, opened = sqlite::open(":memory:", options);
    assert(opened == sqlite::OK);
    let query, prepared = sqlite::prepare(db, "SELECT ?1");
    assert(prepared == sqlite::OK);
    let sizes: i64[7] = [0, 1, 4096, 65536, 1048576, 17, 0];
    for size in sizes {
        assert(sqlite::bind_zeroblob(query, 1, size) == sqlite::OK);
        zeros(query, size); zeros(query, size);
    }
    assert(sqlite::bind_integer(query, 1, 77) == sqlite::OK);
    let bad_sizes: i64[4] = [-1, -9223372036854775807 - 1, 1048577, 9223372036854775807];
    for size in bad_sizes {
        assert(sqlite::bind_zeroblob(query, 1, size) == sqlite::INVALID_INPUT);
        integer(query, 77);
    }
    let bad_indices: i64[5] = [-9223372036854775807 - 1, -1, 0, 2, 9223372036854775807];
    for index in bad_indices {
        assert(sqlite::bind_zeroblob(query, index, 8) == sqlite::INVALID_INPUT);
        integer(query, 77);
    }
    let default_query = sqlite::Statement { .. };
    let wrong_kind = sqlite::Statement { token: db.token };
    assert(sqlite::bind_zeroblob(default_query, 1, 8) == sqlite::INVALID_HANDLE);
    assert(sqlite::bind_zeroblob(wrong_kind, 1, 8) == sqlite::INVALID_HANDLE);
    assert(sqlite::bind_zeroblob(query, 1, 5) == sqlite::OK);
    assert(sqlite::clear_bindings(query) == sqlite::OK);
    assert(sqlite::step(query) == sqlite::ROW && sqlite::column_type(query, 0) == sqlite::NULL);
    var absent: u8[>..] = []; absent.append("old");
    assert(sqlite::column_blob(query, 0, absent) == sqlite::TYPE_MISMATCH && absent.len == 0);
    assert(sqlite::step(query) == sqlite::DONE && sqlite::finalize(query) == sqlite::OK);
    assert(sqlite::bind_zeroblob(query, 1, 8) == sqlite::INVALID_HANDLE);
    let sparse, sparse_code = sqlite::prepare(db, "SELECT ?5");
    assert(sparse_code == sqlite::OK && sqlite::parameter_count(sparse) == 5);
    assert(sqlite::bind_zeroblob(sparse, 1, 19) == sqlite::OK);
    assert(sqlite::bind_zeroblob(sparse, 5, 3) == sqlite::OK);
    zeros(sparse, 3);
    assert(sqlite::finalize(sparse) == sqlite::OK);
    assert(sqlite::execute(db, "CREATE TABLE t(id INTEGER PRIMARY KEY,payload BLOB)") == sqlite::OK);
    assert(sqlite::execute(db, "BEGIN IMMEDIATE") == sqlite::OK);
    let insert, insert_code = sqlite::prepare(db, "INSERT INTO t VALUES(1,?1)");
    assert(insert_code == sqlite::OK && sqlite::bind_zeroblob(insert, 1, 4096) == sqlite::OK);
    assert(sqlite::step(insert) == sqlite::DONE && sqlite::finalize(insert) == sqlite::OK);
    let blob, blob_code = sqlite::blob_open(db, "t", "payload", 1, true);
    assert(blob_code == sqlite::OK && sqlite::blob_write(blob, 2047, "a\0\xffb") == sqlite::OK);
    assert(sqlite::blob_close(blob) == sqlite::OK && sqlite::execute(db, "COMMIT") == sqlite::OK);
    let selected, selected_code = sqlite::prepare(db, "SELECT payload FROM t WHERE id=1");
    assert(selected_code == sqlite::OK && sqlite::step(selected) == sqlite::ROW);
    var bytes: u8[>..] = [];
    assert(sqlite::column_blob(selected, 0, bytes) == sqlite::OK && bytes.len == 4096);
    for i in bytes.len {
        let expected: u8 = if i == 2047 { 'a' } else if i == 2048 { 0 } else if i == 2049 { 255 } else if i == 2050 { 'b' } else { 0 };
        assert(bytes[i] == expected);
    }
    assert(sqlite::step(selected) == sqlite::DONE && sqlite::finalize(selected) == sqlite::OK);
    assert(sqlite::close(db) == sqlite::OK);
    print("sqlite zeroblob public tests passed");
}
