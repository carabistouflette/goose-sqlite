// SPDX-License-Identifier: Apache-2.0
use rusqlite::{Connection, OpenFlags};
use std::time::Duration;

#[derive(Debug, PartialEq)]
pub(crate) struct Policy {
    pub(crate) journal: String,
    pub(crate) synchronous: i64,
    pub(crate) page: i64,
    pub(crate) cache: i64,
    pub(crate) autocheckpoint: i64,
    pub(crate) foreign_keys: i64,
    pub(crate) trusted_schema: i64,
    pub(crate) locking: String,
    pub(crate) busy_ms: i64,
}

pub(crate) fn open(path: &str) -> rusqlite::Result<(Connection, Policy)> {
    let db = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_WRITE
            | OpenFlags::SQLITE_OPEN_NO_MUTEX
            | OpenFlags::SQLITE_OPEN_PRIVATE_CACHE,
    )?;
    db.busy_timeout(Duration::ZERO)?;
    db.execute_batch(
        "PRAGMA synchronous=FULL; PRAGMA cache_size=-2000; \
         PRAGMA foreign_keys=ON; PRAGMA trusted_schema=OFF; \
         PRAGMA locking_mode=NORMAL; PRAGMA wal_autocheckpoint=1000;",
    )?;
    let policy = Policy {
        journal: db.query_row("PRAGMA journal_mode", [], |row| row.get(0))?,
        synchronous: db.query_row("PRAGMA synchronous", [], |row| row.get(0))?,
        page: db.query_row("PRAGMA page_size", [], |row| row.get(0))?,
        cache: db.query_row("PRAGMA cache_size", [], |row| row.get(0))?,
        autocheckpoint: db.query_row("PRAGMA wal_autocheckpoint", [], |row| row.get(0))?,
        foreign_keys: db.query_row("PRAGMA foreign_keys", [], |row| row.get(0))?,
        trusted_schema: db.query_row("PRAGMA trusted_schema", [], |row| row.get(0))?,
        locking: db.query_row("PRAGMA locking_mode", [], |row| row.get(0))?,
        busy_ms: db.query_row("PRAGMA busy_timeout", [], |row| row.get(0))?,
    };
    assert!(policy.journal == "delete" || policy.journal == "wal");
    assert_eq!(policy.synchronous, 2);
    assert_eq!(policy.page, 4096);
    assert_eq!(policy.cache, -2000);
    assert_eq!(policy.autocheckpoint, 1000);
    assert_eq!(policy.foreign_keys, 1);
    assert_eq!(policy.trusted_schema, 0);
    assert_eq!(policy.locking, "normal");
    assert_eq!(policy.busy_ms, 0);
    assert!(db.is_autocommit());
    Ok((db, policy))
}
