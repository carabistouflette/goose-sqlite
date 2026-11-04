// SPDX-License-Identifier: Apache-2.0
import sqlite from "..";
import std;

fn reused_output(db: sqlite::Database) {
    var out:   u8[>..] = []; out.append("old output");
    var first: u8[>..] = []; first.resize(4096, 'a');
    var other: u8[>..] = []; other.resize(4096, 'b');
    var large: u8[>..] = []; large.resize(8192, 'c');
    let stmt, prepared = sqlite::prepare(db, "SELECT ?1, ?2, NULL");
    assert(prepared == sqlite::OK);
    assert(sqlite::column_text(stmt, 0, out) == sqlite::INVALID_STATE && out.len == 0);
    let inputs: (const u8[:])[8] = [first[..], other[..], "small", "", large[..], "tiny", "a\x00b", large[..]];
    for input in inputs {
        assert(sqlite::bind_text(stmt, 1, input) == sqlite::OK);
        assert(sqlite::bind_blob(stmt, 2, input) == sqlite::OK);
        assert(sqlite::step(stmt) == sqlite::ROW);
        assert(sqlite::column_text(stmt, 0, out) == sqlite::OK && out == input);
        assert(sqlite::column_blob(stmt, 1, out) == sqlite::OK && out == input);
        assert(sqlite::step(stmt) == sqlite::DONE);
        assert(sqlite::reset(stmt) == sqlite::OK);
    }
    assert(sqlite::step(stmt) == sqlite::ROW);
    out.resize(2097152, 'z');
    assert(sqlite::column_text(stmt, 0, out) == sqlite::OK && out == large);
    assert(sqlite::column_text(stmt, 2, out) == sqlite::TYPE_MISMATCH && out.len == 0);
    assert(sqlite::column_text(stmt, 0, out) == sqlite::OK && out == large);
    assert(sqlite::column_text(stmt, -1, out) == sqlite::INVALID_INPUT && out.len == 0);
    assert(sqlite::column_text(stmt, 0, out) == sqlite::OK && out == large);
    assert(sqlite::finalize(stmt) == sqlite::OK);
    assert(sqlite::column_text(stmt, 0, out) == sqlite::INVALID_HANDLE && out.len == 0);
}
fn reprepare_columns() {
    let options = sqlite::Options { .. };
    let db, opened = sqlite::open(":memory:", options);
    assert(opened == sqlite::OK);
    assert(sqlite::execute(db, "CREATE TABLE shape(a)") == sqlite::OK);
    assert(sqlite::execute(db, "INSERT INTO shape VALUES(11)") == sqlite::OK);
    let query, prepared = sqlite::prepare(db, "SELECT * FROM shape");
    assert(prepared == sqlite::OK);
    assert(sqlite::execute(db, "ALTER TABLE shape ADD COLUMN b DEFAULT 22") == sqlite::OK);
    assert(sqlite::step(query) == sqlite::ROW && sqlite::column_count(query) == 2);
    let second, second_code = sqlite::column_integer(query, 1);
    assert(second_code == sqlite::OK && second == 22);
    let absent, absent_code = sqlite::column_integer(query, 2);
    assert(absent_code == sqlite::INVALID_INPUT && absent == 0);
    assert(sqlite::reset(query) == sqlite::OK);
    assert(sqlite::execute(db, "ALTER TABLE shape DROP COLUMN b") == sqlite::OK);
    assert(sqlite::step(query) == sqlite::ROW && sqlite::column_count(query) == 1);
    let removed, removed_code = sqlite::column_integer(query, 1);
    assert(removed_code == sqlite::INVALID_INPUT && removed == 0);
    let first, first_code = sqlite::column_integer(query, 0);
    assert(first_code == sqlite::OK && first == 11);
    assert(sqlite::step(query) == sqlite::DONE && sqlite::finalize(query) == sqlite::OK);
    assert(sqlite::close(db) == sqlite::OK);
}
fn main() {
    assert(sqlite::initialize() == sqlite::OK);
    assert(sqlite::initialize() == sqlite::OK);
    reprepare_columns();
    var options = sqlite::Options { .. };
    let db, opened = sqlite::open(":memory:", options);
    assert(opened == sqlite::OK);
    reused_output(db);
    assert(sqlite::execute(db, "CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT, data BLOB, score REAL, absent)") == sqlite::OK);
    assert(sqlite::execute(db, "BEGIN") == sqlite::OK);
    let insert, prepared = sqlite::prepare(db, "INSERT INTO items VALUES(?1, ?2, ?3, ?4, ?5)");
    assert(prepared == sqlite::OK);
    assert(sqlite::close(db) == 5); // SQLITE_BUSY: live statement retains connection.
    assert(sqlite::initialize() == sqlite::OK);
    var name: u8[>..] = []; name.append("a\x00b");
    assert(sqlite::bind_integer(insert, 0, 1) == sqlite::INVALID_INPUT);
    assert(sqlite::bind_integer(insert, 1, -9223372036854775807 - 1) == sqlite::OK);
    assert(sqlite::bind_text(insert, 2, name) == sqlite::OK);
    name[0] = 'z'; // SQLite must have copied it.
    assert(sqlite::bind_blob(insert, 3, "\xff\x00") == sqlite::OK);
    assert(sqlite::bind_float(insert, 4, 1.25) == sqlite::OK);
    assert(sqlite::bind_null(insert, 5) == sqlite::OK);
    assert(sqlite::step(insert) == sqlite::DONE);
    assert(sqlite::step(insert) == sqlite::INVALID_STATE);
    assert(sqlite::bind_null(insert, 1) == sqlite::INVALID_STATE);
    assert(sqlite::clear_bindings(insert) == sqlite::INVALID_STATE);
    assert(sqlite::reset(insert) == sqlite::OK);
    assert(sqlite::bind_integer(insert, 1, 42) == sqlite::OK);
    assert(sqlite::step(insert) == sqlite::DONE); // Other bindings survive reset.
    assert(sqlite::reset(insert) == sqlite::OK);
    assert(sqlite::clear_bindings(insert) == sqlite::OK);
    assert(sqlite::bind_integer(insert, 1, 43) == sqlite::OK);
    assert(sqlite::step(insert) == sqlite::DONE);
    assert(sqlite::finalize(insert) == sqlite::OK);
    assert(sqlite::finalize(insert) == sqlite::INVALID_HANDLE);
    assert(sqlite::execute(db, "COMMIT") == sqlite::OK);
    let query, selected = sqlite::prepare(db, "SELECT * FROM items ORDER BY id; -- trailing comment\n /* accepted */ ");
    assert(selected == sqlite::OK && sqlite::column_count(query) == 5);
    assert(sqlite::column_type(query, 0) == sqlite::INVALID_STATE);
    assert(sqlite::step(query) == sqlite::ROW);
    let id, got_id = sqlite::column_integer(query, 0);
    assert(got_id == sqlite::OK && id == -9223372036854775807 - 1);
    let wrong, wrong_code = sqlite::column_float(query, 0);
    assert(wrong == 0.0 && wrong_code == sqlite::TYPE_MISMATCH);
    var text: u8[>..] = [];
    var blob: u8[>..] = [];
    assert(sqlite::column_text(query, 1, text) == sqlite::OK && text == "a\x00b");
    assert(sqlite::column_blob(query, 2, blob) == sqlite::OK && blob == "\xff\x00");
    let score, got_score = sqlite::column_float(query, 3);
    assert(got_score == sqlite::OK && score == 1.25);
    assert(sqlite::column_type(query, 4) == sqlite::NULL);
    assert(sqlite::column_type(query, -1) == sqlite::INVALID_INPUT);
    assert(sqlite::column_type(query, 5) == sqlite::INVALID_INPUT);
    assert(sqlite::step(query) == sqlite::ROW);
    assert(sqlite::column_text(query, 1, text) == sqlite::OK && text == "a\x00b");
    assert(sqlite::step(query) == sqlite::ROW);
    assert(sqlite::column_type(query, 1) == sqlite::NULL);
    assert(sqlite::column_text(query, 1, text) == sqlite::TYPE_MISMATCH && text.len == 0);
    assert(sqlite::step(query) == sqlite::DONE);
    assert(sqlite::finalize(query) == sqlite::OK);
    assert(blob == "\xff\x00"); // Owned bytes survive finalization.
    let empty, empty_code = sqlite::prepare(db, "SELECT ?1, ?2, ?3");
    assert(empty_code == sqlite::OK);
    assert(sqlite::bind_text(empty, 1, "") == sqlite::OK);
    assert(sqlite::bind_blob(empty, 2, "") == sqlite::OK);
    assert(sqlite::step(empty) == sqlite::ROW);
    assert(sqlite::column_type(empty, 0) == sqlite::TEXT);
    assert(sqlite::column_type(empty, 1) == sqlite::BLOB);
    assert(sqlite::column_type(empty, 2) == sqlite::NULL);
    assert(sqlite::column_text(empty, 0, text) == sqlite::OK && text.len == 0);
    assert(sqlite::column_blob(empty, 1, blob) == sqlite::OK && blob.len == 0);
    assert(sqlite::finalize(empty) == sqlite::OK);
    for sql in ["", "-- only a comment", "SELECT 1; SELECT 2", "SELECT 1;;", "SELECT 1\x00; DELETE FROM items"] {
        let invalid, code = sqlite::prepare(db, sql);
        assert(code == sqlite::INVALID_INPUT && invalid.token == 0);
    }
    for sql in ["SELECT 1 /*unfinished", "SELECT 1; /*", "SELECT 1; /*unfinished", "; SELECT 1", "SELECT '/*not a comment'", "SELECT '--not a comment'"] {
        let accepted, accepted_code = sqlite::prepare(db, sql);
        assert(accepted_code == sqlite::OK && sqlite::step(accepted) == sqlite::ROW);
        assert(sqlite::finalize(accepted) == sqlite::OK);
    }
    for sql in ["PRAGMA trusted_schema=ON", "PRAGMA busy_timeout=99999999", "ATTACH ':memory:' AS extra", "CREATE VIRTUAL TABLE docs USING fts5(body)"] {
        let denied, code = sqlite::prepare(db, sql);
        assert(code == 23 && denied.token == 0); // SQLITE_AUTH.
    }
    let extension, ext_code = sqlite::prepare(db, "SELECT load_extension('bad')");
    if ext_code == sqlite::OK {
        assert(sqlite::step(extension) == 1); // SQLITE_ERROR: not authorized.
        assert(sqlite::finalize(extension) == 1);
    } else { assert(ext_code == 1 && extension.token == 0); }
    assert(sqlite::execute(db, "INSERT INTO items(id) VALUES(999) RETURNING id") == sqlite::INVALID_STATE);
    let unchanged, unchanged_code = sqlite::prepare(db, "SELECT count(*) FROM items WHERE id=999");
    assert(unchanged_code == sqlite::OK && sqlite::step(unchanged) == sqlite::ROW);
    let unchanged_count, unchanged_read = sqlite::column_integer(unchanged, 0);
    assert(unchanged_read == sqlite::OK && unchanged_count == 0);
    assert(sqlite::finalize(unchanged) == sqlite::OK);
    assert(sqlite::execute(db, "CREATE TABLE children(parent INTEGER REFERENCES items(id))") == sqlite::OK);
    assert(sqlite::execute(db, "INSERT INTO children VALUES(999)") == 787); // FK enforcement.
    assert(sqlite::execute(db, "BEGIN") == sqlite::OK);
    assert(sqlite::execute(db, "DELETE FROM items") == sqlite::OK);
    assert(sqlite::execute(db, "ROLLBACK") == sqlite::OK);
    let count, counted = sqlite::prepare(db, "SELECT count(*) FROM items");
    assert(counted == sqlite::OK && sqlite::step(count) == sqlite::ROW);
    let total, total_code = sqlite::column_integer(count, 0);
    assert(total_code == sqlite::OK && total == 3);
    assert(sqlite::finalize(count) == sqlite::OK);
    assert(sqlite::execute(db, "INSERT INTO items(id) VALUES(42)") == 1555); // Extended constraint code.
    var message: u8[>..] = [];
    assert(sqlite::error_message(db, message) == sqlite::OK && message.len > 0);
    let newer, newer_code = sqlite::prepare(db, "SELECT 1");
    assert(newer_code == sqlite::OK);
    assert(sqlite::step(insert) == sqlite::INVALID_HANDLE); // Slot reuse cannot revive stale copy.
    assert(sqlite::finalize(newer) == sqlite::OK);
    assert(sqlite::close(db) == sqlite::OK);
    assert(sqlite::close(db) == sqlite::INVALID_HANDLE);
    assert(sqlite::error_message(db, message) == sqlite::INVALID_HANDLE && message.len == 0);
    for path in ["", "file:test?mode=memory", "abc\x00def"] {
        let invalid, code = sqlite::open(path, options);
        assert(code == sqlite::INVALID_INPUT && invalid.token == 0);
    }
    var ordinary = sqlite::Options { .. };
    let limits, limit_opened = sqlite::open(":memory:", ordinary);
    assert(limit_opened == sqlite::OK);
    let bound, bound_prepared = sqlite::prepare(limits, "SELECT ?1");
    assert(bound_prepared == sqlite::OK);
    var large: u8[>..] = []; large.resize(1048576, 'x');
    assert(sqlite::bind_blob(bound, 1, large) == sqlite::OK);
    assert(sqlite::step(bound) == sqlite::ROW);
    assert(sqlite::column_blob(bound, 0, blob) == sqlite::OK && blob == large);
    assert(sqlite::reset(bound) == sqlite::OK);
    large.push('x');
    assert(sqlite::bind_blob(bound, 1, large) == sqlite::INVALID_INPUT);
    assert(sqlite::finalize(bound) == sqlite::OK);
    var oversized_sql: u8[>..] = []; oversized_sql.append("SELECT 1;");
    oversized_sql.resize(65536, ' ');
    let exact, exact_prepared = sqlite::prepare(limits, oversized_sql);
    assert(exact_prepared == sqlite::OK && sqlite::finalize(exact) == sqlite::OK);
    oversized_sql.push(' ');
    let oversized, oversized_code = sqlite::prepare(limits, oversized_sql);
    assert(oversized_code == sqlite::INVALID_INPUT && oversized.token == 0);
    assert(sqlite::close(limits) == sqlite::OK);
    options.work_budget = 1000;
    let bounded, bounded_code = sqlite::open(":memory:", options);
    assert(bounded_code == sqlite::OK);
    let expensive, expense_code = sqlite::prepare(bounded, "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<1000000) SELECT sum(x) FROM n");
    assert(expense_code == sqlite::OK && sqlite::step(expensive) == 9); // SQLITE_INTERRUPT.
    assert(sqlite::step(expensive) == sqlite::INVALID_STATE);
    assert(sqlite::reset(expensive) == 9);
    assert(sqlite::finalize(expensive) == sqlite::OK);
    assert(sqlite::execute(bounded, "CREATE TABLE recovered(x)") == sqlite::OK);
    assert(sqlite::close(bounded) == sqlite::OK);
    options.busy_ms = -1;
    let invalid, code = sqlite::open(":memory:", options);
    assert(code == sqlite::INVALID_INPUT && invalid.token == 0);
    print("sqlite public API tests passed");
}
