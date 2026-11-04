// SPDX-License-Identifier: Apache-2.0
use rusqlite::{Connection, OpenFlags};
use std::time::Instant;
fn main() -> rusqlite::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let db = Connection::open_with_flags(
        ":memory:",
        OpenFlags::SQLITE_OPEN_READ_WRITE
            | OpenFlags::SQLITE_OPEN_CREATE
            | OpenFlags::SQLITE_OPEN_NO_MUTEX
            | OpenFlags::SQLITE_OPEN_PRIVATE_CACHE,
    )?;
    db.busy_timeout(std::time::Duration::from_millis(1000))?;
    if args.len() == 2 && args[1] == "identity" {
        println!("{}", rusqlite::version());
        println!(
            "{}",
            db.query_row("SELECT sqlite_source_id()", [], |r| r.get::<_, String>(0))?
        );
        let mut q = db.prepare("PRAGMA compile_options")?;
        for opt in q.query_map([], |r| r.get::<_, String>(0))? {
            println!("{}", opt?);
        }
        return Ok(());
    }
    assert_eq!(args.len(), 4);
    let n: i64 = args[1].parse().unwrap();
    let mode = &args[2];
    let size: usize = args[3].parse().unwrap();
    assert!(n > 0 && n <= 10000000 && size <= 65536);
    let mut checksum: i64 = 0;
    let elapsed;
    if mode == "prepare" {
        let start = Instant::now();
        for _ in 0..n {
            let mut s = db.prepare("SELECT 1")?;
            {
                let mut rows = s.query([])?;
                let x: i64 = rows.next()?.unwrap().get(0)?;
                assert_eq!(x, 1);
                checksum += x;
                assert!(rows.next()?.is_none());
            }
            s.finalize()?;
        }
        elapsed = start.elapsed();
    } else if mode == "scalar" {
        let mut s = db.prepare("SELECT ?1")?;
        let start = Instant::now();
        for i in 0..n {
            let mut rows = s.query([i])?;
            let x: i64 = rows.next()?.unwrap().get(0)?;
            assert_eq!(x, i);
            checksum += x;
            assert!(rows.next()?.is_none());
        }
        elapsed = start.elapsed();
        s.finalize()?;
    } else if mode == "text" || mode == "blob" {
        let data = "x".repeat(size);
        let mut s = db.prepare("SELECT ?1")?;
        let start = Instant::now();
        for _ in 0..n {
            let mut rows = if mode == "text" {
                s.query([data.as_str()])?
            } else {
                s.query([data.as_bytes()])?
            };
            let row = rows.next()?.unwrap();
            if mode == "text" {
                let out: String = row.get(0)?;
                assert_eq!(out, data);
                checksum += out.len() as i64;
            } else {
                let out: Vec<u8> = row.get(0)?;
                assert_eq!(out, data.as_bytes());
                checksum += out.len() as i64;
            }
            assert!(rows.next()?.is_none());
        }
        elapsed = start.elapsed();
        s.finalize()?;
    } else if mode == "scan" || mode == "lookup" || mode == "batch" {
        assert!(size >= 2);
        let mut data = vec![b'x'; size];
        data[0] = 0;
        data[size - 1] = 255;
        let mut out = Vec::<u8>::with_capacity(size);
        db.execute_batch("CREATE TABLE items(id INTEGER PRIMARY KEY,group_id INTEGER,payload BLOB); CREATE INDEX by_group ON items(group_id)")?;
        if mode != "batch" {
            let mut insert = db.prepare("INSERT INTO items VALUES(?1,?1%17,?2)")?;
            db.execute_batch("BEGIN")?;
            for i in 0..1024i64 {
                assert_eq!(insert.execute(rusqlite::params![i, &data])?, 1);
            }
            db.execute_batch("COMMIT")?;
            insert.finalize()?;
        }
        if mode == "batch" {
            let mut insert = db.prepare("INSERT INTO items VALUES(?1,?1%17,?2)")?;
            let start = Instant::now();
            db.execute_batch("BEGIN")?;
            for i in 0..n {
                assert_eq!(insert.execute(rusqlite::params![i, &data])?, 1);
            }
            db.execute_batch("COMMIT")?;
            elapsed = start.elapsed();
            insert.finalize()?;
            let mut query = db.prepare("SELECT id,group_id,payload FROM items ORDER BY id")?;
            {
                let mut rows = query.query([])?;
                for i in 0..n {
                    let row = rows.next()?.unwrap();
                    assert_eq!(row.get::<_, i64>(0)?, i);
                    assert_eq!(row.get::<_, i64>(1)?, i % 17);
                    out.clear();
                    out.extend_from_slice(row.get_ref(2)?.as_blob().unwrap());
                    assert_eq!(out, data);
                }
                assert!(rows.next()?.is_none());
            }
            query.finalize()?;
            checksum = n * size as i64;
        } else if mode == "scan" {
            let mut query = db.prepare("SELECT id,payload FROM items ORDER BY id")?;
            let start = Instant::now();
            for _ in 0..n {
                let mut rows = query.query([])?;
                for i in 0..1024i64 {
                    let row = rows.next()?.unwrap();
                    assert_eq!(row.get::<_, i64>(0)?, i);
                    out.clear();
                    out.extend_from_slice(row.get_ref(1)?.as_blob().unwrap());
                    assert_eq!(out, data);
                    checksum += out.len() as i64;
                }
                assert!(rows.next()?.is_none());
            }
            elapsed = start.elapsed();
            query.finalize()?;
        } else {
            let mut query = db.prepare("SELECT id,payload FROM items WHERE id=?1")?;
            let start = Instant::now();
            for i in 0..n {
                let id = (i * 17) % 1024;
                let mut rows = query.query([id])?;
                let row = rows.next()?.unwrap();
                assert_eq!(row.get::<_, i64>(0)?, id);
                out.clear();
                out.extend_from_slice(row.get_ref(1)?.as_blob().unwrap());
                assert_eq!(out, data);
                checksum += out.len() as i64;
                assert!(rows.next()?.is_none());
            }
            elapsed = start.elapsed();
            query.finalize()?;
        }
    } else {
        assert_eq!(mode, "insert");
        db.execute_batch("CREATE TABLE items(x INTEGER)")?;
        let mut s = db.prepare("INSERT INTO items VALUES(?1)")?;
        let start = Instant::now();
        db.execute_batch("BEGIN")?;
        for i in 0..n {
            assert_eq!(s.execute([i])?, 1);
        }
        db.execute_batch("COMMIT")?;
        elapsed = start.elapsed();
        s.finalize()?;
        let (count, sum): (i64, i64) =
            db.query_row("SELECT count(*),sum(x) FROM items", [], |r| {
                Ok((r.get(0)?, r.get(1)?))
            })?;
        assert_eq!(count, n);
        assert_eq!(sum, n * (n - 1) / 2);
        checksum = n;
    }
    println!("{} {}", elapsed.as_nanos(), checksum);
    db.close().map_err(|(_, e)| e)?;
    Ok(())
}
