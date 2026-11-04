// SPDX-License-Identifier: Apache-2.0
import sqlite from "../..";
import std;
import os;
fn main() {
    let argv = args(); assert(argv.len == 4);
    let iterations, valid = parse_int(argv[1]);
    let count, valid_count = parse_int(argv[3]);
    assert(valid && iterations > 0 && iterations <= 10000000);
    assert(valid_count && count > 0 && count <= 524288);
    let incremental = argv[2] == "incremental";
    assert(incremental || argv[2] == "whole");
    var input: u8[>..] = []; input.resize(524288, 0);
    var value: u8      = 0;
    for i in input.len { input[i] = value; if value == 250 { value = 0; } else { value += 1; } }
    let options = sqlite::Options { .. };
    let db, opened = sqlite::open(":memory:", options); assert(opened == sqlite::OK);
    assert(sqlite::execute(db, "CREATE TABLE t(x)") == sqlite::OK);
    let insert, prepared = sqlite::prepare(db, "INSERT INTO t VALUES(?1)");
    assert(prepared == sqlite::OK && sqlite::bind_blob(insert, 1, input) == sqlite::OK);
    assert(sqlite::step(insert) == sqlite::DONE && sqlite::finalize(insert) == sqlite::OK);
    assert(sqlite::execute(db, "BEGIN") == sqlite::OK);
    let query, selected = sqlite::prepare(db, "SELECT x FROM t WHERE rowid=1");
    assert(selected == sqlite::OK && sqlite::step(query) == sqlite::ROW);
    var out: u8[>..] = [];
    assert(sqlite::column_blob(query, 0, out) == sqlite::OK && out == input);
    assert(sqlite::finalize(query) == sqlite::OK);
    let blob, blob_code = sqlite::blob_open(db, "t", "x", 1, false); assert(blob_code == sqlite::OK);
    assert(sqlite::blob_read(blob, 0, 524288, out) == sqlite::OK && out == input);
    assert(sqlite::blob_close(blob) == sqlite::OK);
    var checksum: i64 = 0;
    var elapsed:  i64 = 0;
    if incremental {
        let handle, code = sqlite::blob_open(db, "t", "x", 1, false); assert(code == sqlite::OK);
        out.resize(count);
        let start = clock_ns();
        for i in iterations {
            let offset = (i * 4093) % (524288 - count + 1);
            assert(sqlite::blob_read(handle, offset, count, out) == sqlite::OK);
            assert(out == input[offset..offset + count]);
            checksum += out.len;
        }
        elapsed = clock_ns() - start;
        assert(sqlite::blob_close(handle) == sqlite::OK);
    } else {
        let handle, code = sqlite::prepare(db, "SELECT x FROM t WHERE rowid=1");
        assert(code == sqlite::OK && sqlite::step(handle) == sqlite::ROW);
        out.resize(524288, 0);
        let start = clock_ns();
        for i in iterations {
            let offset = (i * 4093) % (524288 - count + 1);
            assert(sqlite::column_blob(handle, 0, out) == sqlite::OK);
            assert(out[offset..offset + count] == input[offset..offset + count]);
            checksum += count;
        }
        elapsed = clock_ns() - start;
        assert(out == input && sqlite::finalize(handle) == sqlite::OK);
    }
    assert(sqlite::execute(db, "COMMIT") == sqlite::OK && sqlite::close(db) == sqlite::OK);
    print(elapsed, " ", checksum);
}
