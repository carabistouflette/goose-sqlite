// SPDX-License-Identifier: Apache-2.0
use rusqlite::types::ValueRef;
use rusqlite::{params, Connection, Error, ErrorCode, Statement};
use std::error::Error as StdError;
use std::time::Instant;

mod paths;
use paths::open;

fn insert(statement: &mut Statement<'_>, id: i64, payload: &[u8]) -> rusqlite::Result<()> {
    assert_eq!(statement.execute(params![id, payload])?, 1);
    Ok(())
}

fn verify(db: &Connection, payload: &[u8], inserted: usize) -> rusqlite::Result<i64> {
    let mut query = db.prepare("SELECT id,payload FROM items ORDER BY id")?;
    let mut checksum = 0;
    let mut output = Vec::with_capacity(payload.len());
    {
        let mut rows = query.query([])?;
        for position in 0..=inserted {
            let row = rows.next()?.expect("missing stored row");
            let id = match row.get_ref(0)? {
                ValueRef::Integer(value) => value,
                _ => panic!("stored id must have INTEGER storage class"),
            };
            assert_eq!(id, position as i64 - 1);
            match row.get_ref(1)? {
                ValueRef::Blob(bytes) => {
                    output.clear();
                    output.extend_from_slice(bytes);
                }
                _ => panic!("stored payload must have BLOB storage class"),
            }
            assert_eq!(output, payload);
            checksum += id + 2;
        }
        assert!(rows.next()?.is_none(), "unexpected stored row");
    }
    query.finalize()?;
    Ok(checksum)
}

fn main() -> Result<(), Box<dyn StdError>> {
    let args: Vec<String> = std::env::args().collect();
    assert_eq!(args.len(), 5, "expected PATH MODE TRANSACTIONS BATCH");
    let mode = args[2].as_str();
    assert!(matches!(mode, "commit" | "rollback" | "busy"));
    let transactions: usize = args[3].parse()?;
    let batch: usize = args[4].parse()?;
    assert!((1..=10000).contains(&transactions));
    assert!((1..=1024).contains(&batch));
    let total = transactions.checked_mul(batch).expect("row count overflow");
    assert!(total <= 1000000);
    let mut payload = vec![b'x'; 128];
    payload[0] = 0;
    payload[127] = 255;
    let (db, policy) = open(&args[1])?;
    let mut statement = db.prepare("INSERT INTO items VALUES(?1,?2)")?;
    db.execute_batch("BEGIN IMMEDIATE")?;
    insert(&mut statement, -2, &payload)?;
    db.execute_batch("ROLLBACK")?;
    db.execute_batch("BEGIN IMMEDIATE")?;
    db.execute_batch("COMMIT")?;
    db.execute_batch("BEGIN IMMEDIATE")?;
    db.execute_batch("ROLLBACK")?;
    assert!(db.is_autocommit());

    let mut latencies = Vec::with_capacity(transactions);
    let elapsed;
    if mode == "busy" {
        let (blocker, blocker_policy) = open(&args[1])?;
        assert_eq!(blocker_policy, policy);
        blocker.execute_batch("BEGIN IMMEDIATE")?;
        blocker.execute_batch("UPDATE items SET payload=zeroblob(128) WHERE id=-1")?;
        assert_eq!(blocker.changes(), 1);
        let start = Instant::now();
        for _ in 0..transactions {
            let attempt = Instant::now();
            let code = match db.execute_batch("BEGIN IMMEDIATE") {
                Err(Error::SqliteFailure(error, _)) => {
                    assert_eq!(error.code, ErrorCode::DatabaseBusy);
                    assert_eq!(error.extended_code & 255, 5);
                    error.extended_code
                }
                other => panic!("expected SQLITE_BUSY, got {other:?}"),
            };
            assert!(db.is_autocommit());
            latencies.push((attempt.elapsed().as_nanos(), code));
        }
        elapsed = start.elapsed().as_nanos();
        blocker.execute_batch("ROLLBACK")?;
        blocker.close().map_err(|(_, error)| error)?;
        db.execute_batch("BEGIN IMMEDIATE")?;
        insert(&mut statement, 0, &payload)?;
        db.execute_batch("COMMIT")?;
    } else {
        let finish = if mode == "commit" {
            "COMMIT"
        } else {
            "ROLLBACK"
        };
        let start = Instant::now();
        for transaction in 0..transactions {
            let attempt = Instant::now();
            db.execute_batch("BEGIN IMMEDIATE")?;
            for offset in 0..batch {
                insert(
                    &mut statement,
                    (transaction * batch + offset) as i64,
                    &payload,
                )?;
            }
            db.execute_batch(finish)?;
            latencies.push((attempt.elapsed().as_nanos(), 0));
        }
        elapsed = start.elapsed().as_nanos();
    }
    statement.finalize()?;
    assert!(db.is_autocommit());
    let inserted = match mode {
        "commit" => total,
        "busy" => 1,
        _ => 0,
    };
    let checksum = verify(&db, &payload, inserted)?;
    let expected = 1 + inserted as i64 * (inserted as i64 + 3) / 2;
    assert_eq!(checksum, expected);
    db.close().map_err(|(_, error)| error)?;
    assert_eq!(latencies.len(), transactions);
    assert!(elapsed > 0 && latencies.iter().all(|value| value.0 > 0));
    let commits = if mode == "commit" { transactions } else { 0 };
    let busy = if mode == "busy" { transactions } else { 0 };
    let rollbacks = if mode == "rollback" { transactions } else { 0 };
    println!(
        "policy {} {} {} {} {} {} {} {} {}",
        policy.journal,
        policy.synchronous,
        policy.page,
        policy.cache,
        policy.autocheckpoint,
        policy.foreign_keys,
        policy.trusted_schema,
        policy.locking,
        policy.busy_ms
    );
    println!("{elapsed} {checksum} {commits} {busy} {rollbacks}");
    for (value, code) in latencies {
        println!("{value} {code}");
    }
    Ok(())
}
