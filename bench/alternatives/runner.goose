// SPDX-License-Identifier: Apache-2.0
import sqlite from "../..";
import std;
import os;

fn main() {
    let argv = args();
    assert(argv.len == 4);
    let iterations, valid_n = parse_int(argv[1]);
    let size, valid_size = parse_int(argv[3]);
    assert(valid_n && iterations > 0 && iterations <= 10000000);
    assert(valid_size && size >= 0 && size <= 1048576);
    let options = sqlite::Options { work_budget: 100000000 };
    let db, opened = sqlite::open(":memory:", options);
    assert(opened == sqlite::OK);
    var checksum: i64 = 0;
    var start:    i64 = 0;
    var elapsed:  i64 = 0;
    if argv[2] == "prepare" {
        start = clock_ns();
        for i in iterations {
            let stmt, code = sqlite::prepare(db, "SELECT 1");
            assert(code == sqlite::OK && sqlite::step(stmt) == sqlite::ROW);
            let value, read = sqlite::column_integer(stmt, 0);
            assert(read == sqlite::OK);
            checksum += value;
            assert(sqlite::step(stmt) == sqlite::DONE);
            assert(sqlite::finalize(stmt) == sqlite::OK);
        }
        elapsed = clock_ns() - start;
    } else if argv[2] == "scalar" {
        let stmt, code = sqlite::prepare(db, "SELECT ?1");
        assert(code == sqlite::OK);
        start = clock_ns();
        for i in iterations {
            assert(sqlite::bind_integer(stmt, 1, i) == sqlite::OK);
            assert(sqlite::step(stmt) == sqlite::ROW);
            let value, read = sqlite::column_integer(stmt, 0);
            assert(read == sqlite::OK && value == i);
            checksum += value;
            assert(sqlite::step(stmt) == sqlite::DONE);
            assert(sqlite::reset(stmt) == sqlite::OK);
        }
        elapsed = clock_ns() - start;
        assert(sqlite::finalize(stmt) == sqlite::OK);
    } else if argv[2] == "text" || argv[2] == "blob" {
        var input: u8[>..] = []; input.resize(size, 'x');
        var out:   u8[>..] = [];
        let stmt, code = sqlite::prepare(db, "SELECT ?1");
        assert(code == sqlite::OK);
        start = clock_ns();
        for i in iterations {
            let bound = if argv[2] == "text" { sqlite::bind_text(stmt, 1, input) }
                else { sqlite::bind_blob(stmt, 1, input) };
            assert(bound == sqlite::OK);
            assert(sqlite::step(stmt) == sqlite::ROW);
            let copied = if argv[2] == "text" { sqlite::column_text(stmt, 0, out) }
                else { sqlite::column_blob(stmt, 0, out) };
            assert(copied == sqlite::OK && out == input);
            checksum += out.len;
            assert(sqlite::step(stmt) == sqlite::DONE);
            assert(sqlite::reset(stmt) == sqlite::OK);
        }
        elapsed = clock_ns() - start;
        assert(sqlite::finalize(stmt) == sqlite::OK);
    } else {
        assert(argv[2] == "insert");
        assert(sqlite::execute(db, "CREATE TABLE items(x INTEGER)") == sqlite::OK);
        let stmt, code = sqlite::prepare(db, "INSERT INTO items VALUES(?1)");
        assert(code == sqlite::OK);
        start = clock_ns();
        assert(sqlite::execute(db, "BEGIN") == sqlite::OK);
        for i in iterations {
            assert(sqlite::bind_integer(stmt, 1, i) == sqlite::OK);
            assert(sqlite::step(stmt) == sqlite::DONE);
            assert(sqlite::reset(stmt) == sqlite::OK);
        }
        assert(sqlite::execute(db, "COMMIT") == sqlite::OK);
        elapsed = clock_ns() - start;
        assert(sqlite::finalize(stmt) == sqlite::OK);
        let query, selected = sqlite::prepare(db, "SELECT count(*), sum(x) FROM items");
        assert(selected == sqlite::OK && sqlite::step(query) == sqlite::ROW);
        let count, counted = sqlite::column_integer(query, 0);
        assert(counted == sqlite::OK && count == iterations);
        let sum, summed = sqlite::column_integer(query, 1);
        assert(summed == sqlite::OK && sum == iterations * (iterations - 1) / 2);
        checksum = count;
        assert(sqlite::finalize(query) == sqlite::OK);
    }
    assert(sqlite::close(db) == sqlite::OK);
    print(elapsed, " ", checksum);
}
