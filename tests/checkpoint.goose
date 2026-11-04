// SPDX-License-Identifier: Apache-2.0
import sqlite from "..";
import std;
import os;

fn no_progress(db: sqlite::Database, mode: i64, expected: i64) {
    let log, checkpointed, code = sqlite::checkpoint(db, mode);
    assert(code == expected && log == -1 && checkpointed == -1);
}
fn verify(db: sqlite::Database, epoch: i64) {
    let query, prepared = sqlite::prepare(db, "SELECT id,epoch,payload FROM t");
    assert(prepared == sqlite::OK && sqlite::step(query) == sqlite::ROW);
    let id, id_code = sqlite::column_integer(query, 0);
    let actual, epoch_code = sqlite::column_integer(query, 1);
    var bytes: u8[>..] = [];
    assert(sqlite::column_blob(query, 2, bytes) == sqlite::OK && bytes.len == 4);
    assert(id_code == sqlite::OK && id == 1 && epoch_code == sqlite::OK && actual == epoch);
    if epoch == 0 { assert(bytes == "\0\0\0\0"); }
    else { assert(bytes == "\0\x7f\xff\0"); }
    assert(sqlite::step(query) == sqlite::DONE && sqlite::finalize(query) == sqlite::OK);
}
fn main() {
    let argv = args();
    assert(argv.len == 2); // Harness supplies an isolated path for each execution mode.
    let options = sqlite::Options { busy_ms: 0 };
    let db, opened = sqlite::open(":memory:", options);
    assert(opened == sqlite::OK);
    let default_db = sqlite::Database { .. };
    no_progress(default_db, sqlite::CHECKPOINT_PASSIVE, sqlite::INVALID_HANDLE);
    no_progress(db, -1, sqlite::INVALID_INPUT);
    no_progress(db, 4, sqlite::INVALID_INPUT);
    no_progress(db, 9223372036854775807, sqlite::INVALID_INPUT);
    let initial_log, initial_checkpointed, initial = sqlite::checkpoint(db, sqlite::CHECKPOINT_PASSIVE);
    assert(initial_log == -1 && initial_checkpointed == -1);
    if initial == 21 {
        // Older/unrecognized engines fail closed even for a non-WAL database.
        no_progress(db, sqlite::CHECKPOINT_FULL, 21);
        no_progress(db, sqlite::CHECKPOINT_RESTART, 21);
        no_progress(db, sqlite::CHECKPOINT_TRUNCATE, 21);
        assert(sqlite::close(db) == sqlite::OK);
        print("sqlite checkpoint public tests passed (WAL unsupported)");
        return;
    }
    assert(initial == sqlite::OK);
    assert(sqlite::execute(db, "CREATE TABLE local(x)") == sqlite::OK);
    assert(sqlite::execute(db, "INSERT INTO local VALUES(17)") == sqlite::OK);
    assert(sqlite::execute(db, "BEGIN") == sqlite::OK);
    no_progress(db, sqlite::CHECKPOINT_PASSIVE, sqlite::INVALID_STATE);
    assert(sqlite::execute(db, "ROLLBACK") == sqlite::OK);
    let active, active_code = sqlite::prepare(db, "SELECT x FROM local");
    assert(active_code == sqlite::OK && sqlite::step(active) == sqlite::ROW);
    no_progress(db, sqlite::CHECKPOINT_FULL, sqlite::INVALID_STATE);
    let retained, retained_code = sqlite::column_integer(active, 0);
    assert(retained_code == sqlite::OK && retained == 17);
    assert(sqlite::step(active) == sqlite::DONE && sqlite::finalize(active) == sqlite::OK);
    assert(sqlite::close(db) == sqlite::OK);
    no_progress(db, sqlite::CHECKPOINT_PASSIVE, sqlite::INVALID_HANDLE);
    let wal_options = sqlite::Options { wal: true, busy_ms: 0 };
    let writer, writer_code = sqlite::open(argv[1], wal_options);
    assert(writer_code == sqlite::OK);
    assert(sqlite::execute(writer, "CREATE TABLE t(id INTEGER PRIMARY KEY,epoch,payload)") == sqlite::OK);
    assert(sqlite::execute(writer, "INSERT INTO t VALUES(1,0,zeroblob(4))") == sqlite::OK);
    let zero_log, zero_done, zero_code = sqlite::checkpoint(writer, sqlite::CHECKPOINT_TRUNCATE);
    assert(zero_code == sqlite::OK && zero_log == 0 && zero_done == 0);
    let reader, reader_code = sqlite::open(argv[1], options);
    assert(reader_code == sqlite::OK && sqlite::execute(reader, "BEGIN") == sqlite::OK);
    verify(reader, 0); // Acquires an actual old read snapshot.
    assert(sqlite::execute(writer, "UPDATE t SET epoch=1,payload=x'007fff00'") == sqlite::OK);
    // Default open followed immediately by checkpoint must discover the existing WAL.
    let checkpointer, checkpointer_code = sqlite::open(argv[1], options);
    assert(checkpointer_code == sqlite::OK);
    let partial_log, partial_done, partial_code = sqlite::checkpoint(checkpointer, sqlite::CHECKPOINT_PASSIVE);
    assert(partial_code == sqlite::OK && partial_log > partial_done && partial_done >= 0);
    for mode in 3 {
        let busy_log, busy_done, busy_code = sqlite::checkpoint(checkpointer, mode + 1);
        assert(busy_code == 5 && busy_log > busy_done && busy_done >= 0);
        verify(reader, 0);
        verify(writer, 1);
    }
    let automatic, automatic_code = sqlite::autocommit(checkpointer);
    assert(automatic_code == sqlite::OK && automatic);
    assert(sqlite::execute(reader, "COMMIT") == sqlite::OK && sqlite::close(reader) == sqlite::OK);
    let full_log, full_done, full_code = sqlite::checkpoint(checkpointer, sqlite::CHECKPOINT_FULL);
    assert(full_code == sqlite::OK && full_log > 0 && full_log == full_done);
    let restart_log, restart_done, restart_code = sqlite::checkpoint(checkpointer, sqlite::CHECKPOINT_RESTART);
    assert(restart_code == sqlite::OK && restart_log >= 0 && restart_log == restart_done);
    let idle, idle_code = sqlite::prepare(checkpointer, "SELECT ?1");
    assert(idle_code == sqlite::OK && sqlite::bind_integer(idle, 1, 42) == sqlite::OK);
    let truncated_log, truncated_done, truncated_code = sqlite::checkpoint(checkpointer, sqlite::CHECKPOINT_TRUNCATE);
    assert(truncated_code == sqlite::OK && truncated_log == 0 && truncated_done == 0);
    assert(sqlite::step(idle) == sqlite::ROW);
    let answer, answer_code = sqlite::column_integer(idle, 0);
    assert(answer_code == sqlite::OK && answer == 42);
    assert(sqlite::step(idle) == sqlite::DONE && sqlite::finalize(idle) == sqlite::OK);
    verify(checkpointer, 1);
    let readonly_options = sqlite::Options { readonly: true, busy_ms: 0 };
    let readonly, readonly_code = sqlite::open(argv[1], readonly_options);
    assert(readonly_code == sqlite::OK);
    no_progress(readonly, sqlite::CHECKPOINT_PASSIVE, 8);
    assert(sqlite::close(readonly) == sqlite::OK);
    assert(sqlite::execute(checkpointer, "PRAGMA wal_checkpoint(TRUNCATE)") == 23);
    assert(sqlite::close(checkpointer) == sqlite::OK && sqlite::close(writer) == sqlite::OK);
    no_progress(checkpointer, sqlite::CHECKPOINT_PASSIVE, sqlite::INVALID_HANDLE);
    print("sqlite checkpoint public tests passed");
}
