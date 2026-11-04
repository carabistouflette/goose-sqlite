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
struct Blob { token: u64 = 0 }
struct Options {
    readonly:    bool = false,
    wal:         bool = false,
    busy_ms:     i64  = 1000,
    work_budget: i64  = 1000000,
}
extern fn native_initialize() -> i64 = "gq_initialize";
extern fn native_open(path: const u8[:], readonly: i64, busy_ms: i64, budget: i64, wal: i64, token: u64&) -> i64 = "gq_open_config";
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

// Call on the startup thread, after native SQLite configuration and before workers.
fn initialize() -> i64 { return native_initialize(); }
fn open(path: const u8[:], options: const Options&) -> Database, i64 {
    var token: u64 = 0;
    let code = native_open(path, if options.readonly { 1 } else { 0 }, options.busy_ms, options.work_budget, if options.wal { 1 } else { 0 }, token);
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
extern fn native_fetch(token: u64, column: i64, kind: i64, out: u8[:], length: i64&) -> i64 = "gq_fetch";
fn column_bytes(stmt: Statement, column: i64, kind: i64, out: u8[>..]&) -> i64 {
    var size: i64 = 0;
    var available = min(out.len, 1048576);
    var code = native_fetch(stmt.token, column, kind, out[..available], size);
    if code == LIMIT && size > available && size <= 1048576 {
        out.resize(size, 0);
        available = out.len;
        code = native_fetch(stmt.token, column, kind, out[..available], size);
    }
    if code != OK { out.clear(); return code; }
    if size < 0 || size > available { out.clear(); return LIMIT; }
    out.resize(size);
    return OK;
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
// and RETURNING; this helper rejects result columns before stepping.
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

extern fn native_parameter_count(token: u64) -> i64 = "gq_parameter_count";
extern fn native_parameter_index(token: u64, name: const u8[:]) -> i64 = "gq_parameter_index";
extern fn native_name(token: u64, column: i64, out: u8[:], length: i64&) -> i64 = "gq_name";
extern fn native_status(token: u64, kind: i64, value: i64&) -> i64 = "gq_status";
fn parameter_count(stmt: Statement) -> i64 { return native_parameter_count(stmt.token); }
fn parameter_index(stmt: Statement, name: const u8[:]) -> i64 { return native_parameter_index(stmt.token, name); }
fn column_name(stmt: Statement, column: i64, out: u8[>..]&) -> i64 {
    var length: i64 = 0;
    out.resize(256, 0);
    var code = native_name(stmt.token, column, out[..], length);
    if code == LIMIT && length > 256 && length <= 65536 {
        out.resize(length, 0);
        code = native_name(stmt.token, column, out[..], length);
    }
    if code != OK { out.clear(); return code; }
    if length < 0 || length > out.len { out.clear(); return LIMIT; }
    out.resize(length);
    return OK;
}
fn changes(db: Database) -> i64, i64 {
    var value: i64 = 0; let code = native_status(db.token, 0, value); return value, code;
}
fn last_insert_rowid(db: Database) -> i64, i64 {
    var value: i64 = 0; let code = native_status(db.token, 1, value); return value, code;
}
fn autocommit(db: Database) -> bool, i64 {
    var value: i64 = 0; let code = native_status(db.token, 2, value); return value != 0, code;
}

// Incremental access is byte oriented and limited to main schema rowid tables.
// Writable access requires an explicit transaction and bypasses SQL CHECKs/triggers.
extern fn native_blob_open(token: u64, table: const u8[:], column: const u8[:], rowid: i64, writable: i64, out: u64&) -> i64 = "gq_blob_open";
extern fn native_blob_close(token: u64) -> i64 = "gq_blob_close";
extern fn native_blob_size(token: u64, size: i64&) -> i64 = "gq_blob_size";
extern fn native_blob_read(token: u64, offset: i64, out: u8[:]) -> i64 = "gq_blob_read";
extern fn native_blob_write(token: u64, offset: i64, bytes: const u8[:]) -> i64 = "gq_blob_write";
extern fn native_backup(source: u64, destination: u64, max_pages: i64) -> i64 = "gq_backup";
fn blob_open(db: Database, table: const u8[:], column: const u8[:], rowid: i64, writable: bool) -> Blob, i64 {
    var token: u64 = 0;
    let code = native_blob_open(db.token, table, column, rowid, if writable { 1 } else { 0 }, token);
    return Blob { token }, code;
}
fn blob_close(blob: Blob) -> i64 { return native_blob_close(blob.token); }
fn blob_size(blob: Blob) -> i64, i64 {
    var size: i64 = 0;
    let code = native_blob_size(blob.token, size);
    return size, code;
}
fn blob_read(blob: Blob, offset: i64, count: i64, out: u8[>..]&) -> i64 {
    if offset < 0 || count < 0 || count > 1048576 { out.clear(); return INVALID_INPUT; }
    out.resize(count, 0);
    let code = native_blob_read(blob.token, offset, out[..]);
    if code != OK { out.clear(); }
    return code;
}
fn blob_write(blob: Blob, offset: i64, bytes: const u8[:]) -> i64 {
    return native_blob_write(blob.token, offset, bytes);
}
// Whole main database copy. Incomplete copies roll back destination changes.
fn backup(source: Database, destination: Database, max_pages: i64) -> i64 {
    return native_backup(source.token, destination.token, max_pages);
}

// SQLite statement counters are engine-sized; VM steps above INT_MAX are undefined.
const STMT_FULLSCAN_STEPS: i64 = 1;
const STMT_SORTS:          i64 = 2;
const STMT_AUTOINDEX_ROWS: i64 = 3;
const STMT_VM_STEPS:       i64 = 4;
const STMT_REPREPARES:     i64 = 5;
const STMT_RUNS:           i64 = 6;
const STMT_MEMORY_USED:    i64 = 99;
extern fn native_statement_status(token: u64, metric: i64, reset: i64, value: i64&) -> i64 = "gq_stmt_status";
fn statement_status(stmt: Statement, metric: i64, reset_counter: bool) -> i64, i64 {
    var value: i64 = 0;
    let code = native_statement_status(stmt.token, metric, if reset_counter { 1 } else { 0 }, value);
    return value, code;
}
