// SPDX-License-Identifier: Apache-2.0
namespace sqlite;
import std;

// Nonnegative codes are SQLite result codes (including extended codes).
const OK:             i64 = 0;
const ROW:            i64 = 100;
const DONE:           i64 = 101;
const INVALID_INPUT:  i64 = -1;
const INVALID_HANDLE: i64 = -2;
const INVALID_STATE:  i64 = -3;
const TYPE_MISMATCH:  i64 = -4;
const LIMIT:          i64 = -5;
const INTEGER:        i64 = 1;
const FLOAT:          i64 = 2;
const TEXT:           i64 = 3;
const BLOB:           i64 = 4;
const NULL:           i64 = 5;

struct Database { token: u64 = 0 }
struct Statement { token: u64 = 0 }
struct Options {
    readonly:    bool = false,
    busy_ms:     i64  = 1000,
    work_budget: i64  = 1000000,
}
extern fn native_open(path: const u8[:], readonly: i64, busy_ms: i64, budget: i64, token: u64&) -> i64 = "gq_open";
extern fn native_close(token: u64) -> i64 = "gq_close";
extern fn native_prepare(token: u64, sql: const u8[:], out: u64&) -> i64 = "gq_prepare";
extern fn native_finalize(token: u64) -> i64 = "gq_finalize";
extern fn native_reset(token: u64) -> i64 = "gq_reset";
extern fn native_clear(token: u64) -> i64 = "gq_clear";
extern fn native_bind(token: u64, index: i64, kind: i64, integer: i64, real: f64, bytes: const u8[:]) -> i64 = "gq_bind";
extern fn native_step(token: u64) -> i64 = "gq_step";
extern fn native_columns(token: u64) -> i64 = "gq_columns";
extern fn native_type(token: u64, column: i64) -> i64 = "gq_type";
extern fn native_integer(token: u64, column: i64, value: i64&) -> i64 = "gq_integer";
extern fn native_real(token: u64, column: i64, value: f64&) -> i64 = "gq_real";
extern fn native_size(token: u64, column: i64, kind: i64, size: i64&) -> i64 = "gq_size";
extern fn native_copy(token: u64, column: i64, kind: i64, out: u8[:]) -> i64 = "gq_copy";
extern fn native_message(token: u64, out: u8[:]) -> i64 = "gq_message";

fn open(path: const u8[:], options: const Options&) -> Database, i64 {
    var token: u64 = 0;
    let code = native_open(path, if options.readonly { 1 } else { 0 }, options.busy_ms, options.work_budget, token);
    return Database { token }, code;
}
fn close(db: Database) -> i64 { return native_close(db.token); }
fn prepare(db: Database, sql: const u8[:]) -> Statement, i64 {
    var token: u64 = 0;
    let code = native_prepare(db.token, sql, token);
    return Statement { token }, code;
}
fn finalize(stmt: Statement) -> i64 { return native_finalize(stmt.token); }
fn reset(stmt: Statement) -> i64 { return native_reset(stmt.token); }
fn clear_bindings(stmt: Statement) -> i64 { return native_clear(stmt.token); }
fn bind_null(stmt: Statement, index: i64) -> i64 { return native_bind(stmt.token, index, NULL, 0, 0.0, ""); }
fn bind_integer(stmt: Statement, index: i64, value: i64) -> i64 { return native_bind(stmt.token, index, INTEGER, value, 0.0, ""); }
fn bind_float(stmt: Statement, index: i64, value: f64) -> i64 { return native_bind(stmt.token, index, FLOAT, 0, value, ""); }
fn bind_text(stmt: Statement, index: i64, value: const u8[:]) -> i64 { return native_bind(stmt.token, index, TEXT, 0, 0.0, value); }
fn bind_blob(stmt: Statement, index: i64, value: const u8[:]) -> i64 { return native_bind(stmt.token, index, BLOB, 0, 0.0, value); }
fn step(stmt: Statement) -> i64 { return native_step(stmt.token); }
fn column_count(stmt: Statement) -> i64 { return native_columns(stmt.token); }
fn column_type(stmt: Statement, column: i64) -> i64 { return native_type(stmt.token, column); }
fn column_integer(stmt: Statement, column: i64) -> i64, i64 {
    var value: i64 = 0;
    let code = native_integer(stmt.token, column, value);
    return value, code;
}
fn column_float(stmt: Statement, column: i64) -> f64, i64 {
    var value: f64 = 0.0;
    let code = native_real(stmt.token, column, value);
    return value, code;
}
fn column_bytes(stmt: Statement, column: i64, kind: i64, out: u8[>..]&) -> i64 {
    out.clear();
    var size: i64 = 0;
    let code = native_size(stmt.token, column, kind, size);
    if code != OK { return code; }
    if size < 0 || size > 1048576 { return LIMIT; }
    out.resize(size, 0);
    let copied = native_copy(stmt.token, column, kind, out[..]);
    if copied != OK { out.clear(); }
    return copied;
}
fn column_text(stmt: Statement, column: i64, out: u8[>..]&) -> i64 { return column_bytes(stmt, column, TEXT, out); }
fn column_blob(stmt: Statement, column: i64, out: u8[>..]&) -> i64 { return column_bytes(stmt, column, BLOB, out); }
fn error_message(db: Database, out: u8[>..]&) -> i64 {
    out.clear(); out.resize(4096, 0);
    let count = native_message(db.token, out[..]);
    if count < 0 { out.clear(); return count; }
    out.resize(count);
    return OK;
}
// Execute a single statement that returns no rows. Use prepare/step for queries
// and RETURNING; this helper reports INVALID_STATE if a row is produced.
fn execute(db: Database, sql: const u8[:]) -> i64 {
    let stmt, prepared = prepare(db, sql);
    if prepared != OK { return prepared; }
    if column_count(stmt) > 0 {
        finalize(stmt);
        return INVALID_STATE;
    }
    let stepped = step(stmt);
    let finished = finalize(stmt);
    if stepped == ROW { return INVALID_STATE; }
    if stepped != DONE { return stepped; }
    return finished;
}
