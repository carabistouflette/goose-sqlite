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
    } else if argv[2] == "scan" || argv[2] == "lookup" || argv[2] == "batch" {
        assert(size >= 2);
        var input: u8[>..] = []; input.resize(size, 'x'); input[0] = 0; input[size - 1] = 255;
        var out:   u8[>..] = []; out.resize(size, 0);
        assert(sqlite::execute(db, "CREATE TABLE items(id INTEGER PRIMARY KEY,group_id INTEGER,payload BLOB)") == sqlite::OK);
        assert(sqlite::execute(db, "CREATE INDEX by_group ON items(group_id)") == sqlite::OK);
        if argv[2] != "batch" {
            let insert, code = sqlite::prepare(db, "INSERT INTO items VALUES(?1,?1%17,?2)");
            assert(code == sqlite::OK && sqlite::execute(db, "BEGIN") == sqlite::OK);
            for i in 1024 {
                assert(sqlite::bind_integer(insert, 1, i) == sqlite::OK);
                assert(sqlite::bind_blob(insert, 2, input) == sqlite::OK);
                assert(sqlite::step(insert) == sqlite::DONE && sqlite::reset(insert) == sqlite::OK);
            }
            assert(sqlite::execute(db, "COMMIT") == sqlite::OK && sqlite::finalize(insert) == sqlite::OK);
        }
        if argv[2] == "batch" {
            let insert, code = sqlite::prepare(db, "INSERT INTO items VALUES(?1,?1%17,?2)");
            assert(code == sqlite::OK);
            start = clock_ns(); assert(sqlite::execute(db, "BEGIN") == sqlite::OK);
            for i in iterations {
                assert(sqlite::bind_integer(insert, 1, i) == sqlite::OK);
                assert(sqlite::bind_blob(insert, 2, input) == sqlite::OK);
                assert(sqlite::step(insert) == sqlite::DONE && sqlite::reset(insert) == sqlite::OK);
            }
            assert(sqlite::execute(db, "COMMIT") == sqlite::OK); elapsed = clock_ns() - start;
            assert(sqlite::finalize(insert) == sqlite::OK);
            let query, selected = sqlite::prepare(db, "SELECT id,group_id,payload FROM items ORDER BY id");
            assert(selected == sqlite::OK);
            for i in iterations {
                assert(sqlite::step(query) == sqlite::ROW);
                let id, id_code = sqlite::column_integer(query, 0);
                let group, group_code = sqlite::column_integer(query, 1);
                assert(id_code == sqlite::OK && id == i && group_code == sqlite::OK && group == i % 17);
                assert(sqlite::column_blob(query, 2, out) == sqlite::OK && out == input);
            }
            assert(sqlite::step(query) == sqlite::DONE && sqlite::finalize(query) == sqlite::OK);
            checksum = iterations * size;
        } else if argv[2] == "scan" {
            let query, selected = sqlite::prepare(db, "SELECT id,payload FROM items ORDER BY id");
            assert(selected == sqlite::OK);
            start = clock_ns();
            for pass in iterations {
                for i in 1024 {
                    assert(sqlite::step(query) == sqlite::ROW);
                    let id, id_code = sqlite::column_integer(query, 0);
                    assert(id_code == sqlite::OK && id == i);
                    assert(sqlite::column_blob(query, 1, out) == sqlite::OK && out == input);
                    checksum += out.len;
                }
                assert(sqlite::step(query) == sqlite::DONE && sqlite::reset(query) == sqlite::OK);
            }
            elapsed = clock_ns() - start;
            assert(sqlite::finalize(query) == sqlite::OK);
        } else {
            let query, selected = sqlite::prepare(db, "SELECT id,payload FROM items WHERE id=?1");
            assert(selected == sqlite::OK);
            start = clock_ns();
            for i in iterations {
                let wanted = (i * 17) % 1024;
                assert(sqlite::bind_integer(query, 1, wanted) == sqlite::OK && sqlite::step(query) == sqlite::ROW);
                let id, id_code = sqlite::column_integer(query, 0);
                assert(id_code == sqlite::OK && id == wanted);
                assert(sqlite::column_blob(query, 1, out) == sqlite::OK && out == input);
                checksum += out.len;
                assert(sqlite::step(query) == sqlite::DONE && sqlite::reset(query) == sqlite::OK);
            }
            elapsed = clock_ns() - start;
            assert(sqlite::finalize(query) == sqlite::OK);
        }
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
