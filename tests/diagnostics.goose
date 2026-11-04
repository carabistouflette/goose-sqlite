// SPDX-License-Identifier: Apache-2.0
import sqlite from "..";
import std;
fn main() {
    let options = sqlite::Options { .. };
    let db, opened = sqlite::open(":memory:", options);
    assert(opened == sqlite::OK);
    assert(sqlite::execute(db, "CREATE TABLE t(x INTEGER)") == sqlite::OK);
    assert(sqlite::execute(db, "INSERT INTO t VALUES(3),(1),(4),(2)") == sqlite::OK);
    let scan, prepared = sqlite::prepare(db, "SELECT x FROM t ORDER BY x");
    assert(prepared == sqlite::OK);
    let default_stmt = sqlite::Statement { .. };
    let missing, missing_code = sqlite::statement_status(default_stmt, sqlite::STMT_RUNS, false);
    assert(missing_code == sqlite::INVALID_HANDLE && missing == 0);
    let wrong_kind = sqlite::Statement { token: db.token };
    let wrong, wrong_code = sqlite::statement_status(wrong_kind, sqlite::STMT_RUNS, false);
    assert(wrong_code == sqlite::INVALID_HANDLE && wrong == 0);
    let before, before_code = sqlite::statement_status(scan, sqlite::STMT_RUNS, false);
    assert(before_code == sqlite::OK && before == 0);
    for i in 4 {
        assert(sqlite::step(scan) == sqlite::ROW);
        let active, active_code = sqlite::statement_status(scan, sqlite::STMT_RUNS, false);
        assert(active_code == sqlite::OK && active == 1);
        let value, read = sqlite::column_integer(scan, 0);
        assert(read == sqlite::OK && value == i + 1);
    }
    assert(sqlite::step(scan) == sqlite::DONE);
    let steps, steps_code = sqlite::statement_status(scan, sqlite::STMT_FULLSCAN_STEPS, false);
    let sorts, sorts_code = sqlite::statement_status(scan, sqlite::STMT_SORTS, false);
    let vm, vm_code = sqlite::statement_status(scan, sqlite::STMT_VM_STEPS, false);
    let runs, runs_code = sqlite::statement_status(scan, sqlite::STMT_RUNS, true);
    assert(steps_code == sqlite::OK && steps > 0 && sorts_code == sqlite::OK && sorts == 1);
    assert(vm_code == sqlite::OK && vm > 0 && runs_code == sqlite::OK && runs == 1);
    let cleared, cleared_code = sqlite::statement_status(scan, sqlite::STMT_RUNS, false);
    assert(cleared_code == sqlite::OK && cleared == 0);
    let bytes, bytes_code = sqlite::statement_status(scan, sqlite::STMT_MEMORY_USED, true);
    assert(bytes_code == sqlite::OK && bytes > 0);
    let retained, retained_code = sqlite::statement_status(scan, sqlite::STMT_MEMORY_USED, false);
    assert(retained_code == sqlite::OK && retained == bytes);
    let bad, bad_code = sqlite::statement_status(scan, 7, false);
    assert(bad_code == sqlite::INVALID_INPUT && bad == 0);
    assert(sqlite::reset(scan) == sqlite::OK && sqlite::step(scan) == sqlite::ROW);
    let again, again_code = sqlite::statement_status(scan, sqlite::STMT_RUNS, false);
    assert(again_code == sqlite::OK && again == 1);
    assert(sqlite::finalize(scan) == sqlite::OK);
    let stale, stale_code = sqlite::statement_status(scan, sqlite::STMT_RUNS, false);
    assert(stale_code == sqlite::INVALID_HANDLE && stale == 0);
    assert(sqlite::execute(db, "CREATE UNIQUE INDEX unique_x ON t(x)") == sqlite::OK);
    let failed, failed_prepare = sqlite::prepare(db, "INSERT INTO t VALUES(1)");
    assert(failed_prepare == sqlite::OK && sqlite::step(failed) == 2067);
    let failed_runs, failed_runs_code = sqlite::statement_status(failed, sqlite::STMT_RUNS, false);
    assert(failed_runs_code == sqlite::OK && failed_runs == 1);
    assert(sqlite::finalize(failed) == 2067);
    assert(sqlite::close(db) == sqlite::OK);
    print("sqlite statement diagnostics passed");
}
