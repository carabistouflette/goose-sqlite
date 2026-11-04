// SPDX-License-Identifier: Apache-2.0
import sqlite from "..";
import std;

fn main() {
    let options = sqlite::Options { .. };
    let db, opened = sqlite::open(":memory:", options);
    assert(opened == sqlite::OK);
    assert(sqlite::execute(db, "CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT NOT NULL)") == sqlite::OK);
    let insert, prepared = sqlite::prepare(db, "INSERT INTO items(name) VALUES(?1)");
    assert(prepared == sqlite::OK);
    assert(sqlite::bind_text(insert, 1, "Goose") == sqlite::OK);
    assert(sqlite::step(insert) == sqlite::DONE);
    assert(sqlite::finalize(insert) == sqlite::OK);
    let query, selected = sqlite::prepare(db, "SELECT id, name FROM items");
    assert(selected == sqlite::OK);
    var name: u8[>..] = [];
    var stepped = sqlite::step(query);
    while stepped == sqlite::ROW {
        let id, read = sqlite::column_integer(query, 0);
        assert(read == sqlite::OK);
        assert(sqlite::column_text(query, 1, name) == sqlite::OK);
        print(id, ": ", name);
        stepped = sqlite::step(query);
    }
    assert(stepped == sqlite::DONE);
    assert(sqlite::finalize(query) == sqlite::OK);
    assert(sqlite::close(db) == sqlite::OK);
}
