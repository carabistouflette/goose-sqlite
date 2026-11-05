// SPDX-License-Identifier: Apache-2.0
#[path = "../paths.rs"]
mod paths;
use rusqlite::types::ValueRef;
use rusqlite::{params, Connection, Error, ErrorCode, Statement};
use std::error::Error as StdError;
use std::io::{self, BufRead, Read, Write};
use std::time::Instant;

type Result<T> = std::result::Result<T, Box<dyn StdError>>;

struct Payloads {
    data: Vec<u8>,
    rows: usize,
    attempts: usize,
}
impl Payloads {
    fn new(attempts: usize, rows: usize) -> Self {
        let mut data = Vec::with_capacity((attempts + 1) * rows * 128);
        for epoch in 0..=attempts {
            for id in 0..rows {
                data.push(0);
                for j in 1..127 {
                    data.push(((epoch * 17 + id * 31 + j * 7) % 256) as u8);
                }
                data.push(255);
            }
        }
        Self {
            data,
            rows,
            attempts,
        }
    }
    fn get(&self, epoch: i64, id: usize) -> &[u8] {
        assert!(epoch >= 0 && epoch <= self.attempts as i64 && id < self.rows);
        let start = (epoch as usize * self.rows + id) * 128;
        &self.data[start..start + 128]
    }
}

fn event(out: &mut impl Write, line: impl AsRef<str>) -> Result<()> {
    writeln!(out, "{}", line.as_ref())?;
    out.flush()?;
    Ok(())
}
fn command(input: &mut impl BufRead) -> Result<String> {
    let mut value = String::new();
    if (&mut *input).take(9).read_line(&mut value)? == 0 {
        return Err("unexpected control EOF".into());
    }
    if !value.ends_with('\n') || value.len() > 8 {
        return Err("malformed command".into());
    }
    value.pop();
    if value.ends_with('\r') {
        value.pop();
    }
    Ok(value)
}
fn stage_error(stage: &str, error: Error) -> Box<dyn StdError> {
    let code = match &error {
        Error::SqliteFailure(e, _) => e.extended_code,
        _ => -1,
    };
    eprintln!("FAIL {stage} {code}: {error}");
    Box::new(error)
}
fn control(db: &Connection, sql: &str, stage: &str) -> Result<()> {
    db.execute_batch(sql).map_err(|e| stage_error(stage, e))?;
    Ok(())
}
fn begin(db: &Connection, sql: &str) -> Result<i32> {
    match db.execute_batch(sql) {
        Ok(()) => Ok(0),
        Err(Error::SqliteFailure(error, _)) if error.code == ErrorCode::DatabaseBusy => {
            assert!(error.extended_code >= 0 && error.extended_code & 255 == 5);
            assert!(db.is_autocommit(), "BEGIN BUSY left transaction active");
            Ok(error.extended_code)
        }
        Err(error) => Err(stage_error("begin", error)),
    }
}
fn update(statement: &mut Statement<'_>, epoch: i64, payloads: &Payloads) -> Result<()> {
    for id in 0..payloads.rows {
        let changed = statement
            .execute(params![epoch, payloads.get(epoch, id), id as i64])
            .map_err(|e| stage_error("update", e))?;
        assert_eq!(changed, 1, "UPDATE must affect one row");
    }
    Ok(())
}
fn scan(statement: &mut Statement<'_>, payloads: &Payloads, output: &mut Vec<u8>) -> Result<i64> {
    let mut rows = statement.query([]).map_err(|e| stage_error("read", e))?;
    let mut common = None;
    for id in 0..payloads.rows {
        let row = rows
            .next()
            .map_err(|e| stage_error("read", e))?
            .ok_or("missing row")?;
        match row.get_ref(0)? {
            ValueRef::Integer(value) => assert_eq!(value, id as i64),
            _ => return Err("noninteger ID".into()),
        }
        let epoch = match row.get_ref(1)? {
            ValueRef::Integer(value) => value,
            _ => return Err("noninteger epoch".into()),
        };
        if let Some(expected) = common {
            assert_eq!(epoch, expected, "mixed snapshot epochs");
        } else {
            common = Some(epoch);
        }
        match row.get_ref(2)? {
            ValueRef::Blob(bytes) => {
                output.clear();
                output.extend_from_slice(bytes);
            }
            _ => return Err("nonblob payload".into()),
        }
        assert_eq!(output.as_slice(), payloads.get(epoch, id));
    }
    assert!(
        rows.next().map_err(|e| stage_error("read", e))?.is_none(),
        "extra row"
    );
    Ok(common.expect("nonempty seeded table"))
}
fn read_transaction(
    db: &Connection,
    query: &mut Statement<'_>,
    payloads: &Payloads,
    output: &mut Vec<u8>,
) -> Result<(i32, i64)> {
    let code = begin(db, "BEGIN DEFERRED")?;
    if code != 0 {
        return Ok((code, -1));
    }
    let epoch = scan(query, payloads, output)?;
    control(db, "COMMIT", "read-commit")?;
    Ok((0, epoch))
}

fn qualify_writer(
    db: &Connection,
    statement: &mut Statement<'_>,
    payloads: &Payloads,
    input: &mut impl BufRead,
    out: &mut impl Write,
) -> Result<()> {
    for expected in ["C", "U", "B", "S"] {
        assert_eq!(
            command(input)?,
            expected,
            "out-of-order qualification command"
        );
        match expected {
            "C" => {
                assert_eq!(begin(db, "BEGIN IMMEDIATE")?, 0);
                update(statement, 1, payloads)?;
                control(db, "COMMIT", "qualification-commit")?;
                assert!(db.is_autocommit());
                event(out, "COMMITTED 1")?;
            }
            "U" => {
                assert_eq!(begin(db, "BEGIN IMMEDIATE")?, 0);
                update(statement, 2, payloads)?;
                assert!(!db.is_autocommit());
                event(out, "DIRTY 2")?;
            }
            "B" => {
                control(db, "ROLLBACK", "qualification-rollback")?;
                assert!(db.is_autocommit());
                event(out, "ROLLED_BACK 2")?;
            }
            "S" => {}
            _ => unreachable!(),
        }
    }
    Ok(())
}
fn qualify_reader(
    db: &Connection,
    query: &mut Statement<'_>,
    payloads: &Payloads,
    output: &mut Vec<u8>,
    input: &mut impl BufRead,
    out: &mut impl Write,
) -> Result<()> {
    assert_eq!(command(input)?, "H");
    assert_eq!(begin(db, "BEGIN DEFERRED")?, 0);
    assert_eq!(scan(query, payloads, output)?, 0);
    assert!(!db.is_autocommit());
    event(out, "HELD 0")?;
    assert_eq!(command(input)?, "V");
    assert_eq!(scan(query, payloads, output)?, 0);
    event(out, "VERIFIED 0")?;
    for fresh in 0..3 {
        assert_eq!(command(input)?, "F");
        if fresh == 0 {
            control(db, "COMMIT", "held-read-commit")?;
        }
        assert_eq!(read_transaction(db, query, payloads, output)?, (0, 1));
        event(out, "FRESH 1")?;
    }
    assert_eq!(command(input)?, "S");
    Ok(())
}
fn mixed_writer(
    db: &Connection,
    statement: &mut Statement<'_>,
    payloads: &Payloads,
    input: &mut impl BufRead,
    out: &mut impl Write,
) -> Result<()> {
    assert_eq!(command(input)?, "G");
    event(out, "START writer")?;
    let mut commits = 0;
    let mut busy = 0;
    let window = Instant::now();
    for index in 1..=payloads.attempts {
        let started = Instant::now();
        let code = begin(db, "BEGIN IMMEDIATE")?;
        if code == 0 {
            update(statement, commits + 1, payloads)?;
            control(db, "COMMIT", "write-commit")?;
            commits += 1;
        } else {
            busy += 1;
        }
        let duration = started.elapsed().as_nanos();
        assert!(duration > 0);
        event(out, format!("W {index} {duration} {code} {commits}"))?;
    }
    let elapsed = window.elapsed().as_nanos();
    assert!(elapsed > 0 && commits + busy == payloads.attempts as i64);
    event(out, format!("DONE writer {elapsed} {commits} {busy}"))?;
    Ok(())
}
fn mixed_reader(
    db: &Connection,
    query: &mut Statement<'_>,
    payloads: &Payloads,
    read_cap: usize,
    output: &mut Vec<u8>,
    input: &mut impl BufRead,
    out: &mut impl Write,
) -> Result<()> {
    assert_eq!(command(input)?, "G");
    event(out, "START reader")?;
    let mut successes = 0;
    let mut busy = 0;
    let mut last_epoch = 0;
    let window = Instant::now();
    for index in 1..=read_cap {
        let started = Instant::now();
        let (code, epoch) = read_transaction(db, query, payloads, output)?;
        if code == 0 {
            assert!(epoch >= last_epoch, "reader epoch regressed");
            last_epoch = epoch;
            successes += 1;
        } else {
            assert_eq!(epoch, -1);
            busy += 1;
        }
        let duration = started.elapsed().as_nanos();
        assert!(duration > 0);
        event(out, format!("R {index} {duration} {code} {epoch}"))?;
        match command(input)?.as_str() {
            "S" => {
                let elapsed = window.elapsed().as_nanos();
                assert!(elapsed > 0);
                event(out, format!("DONE reader {elapsed} {successes} {busy}"))?;
                return Ok(());
            }
            "N" if index < read_cap => {}
            "N" => return Err("reader operation cap reached while work remained".into()),
            _ => return Err("unexpected reader control command".into()),
        }
    }
    unreachable!()
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    assert_eq!(
        args.len(),
        7,
        "expected PATH ROLE PHASE ATTEMPTS ROWS READ_CAP"
    );
    let role = args[2].as_str();
    let phase = args[3].as_str();
    assert!(matches!(role, "reader" | "writer"));
    assert!(matches!(phase, "qualify" | "mixed"));
    let attempts: usize = args[4].parse()?;
    let row_count: usize = args[5].parse()?;
    let read_cap: usize = args[6].parse()?;
    assert!((8..=4096).contains(&attempts) && (1..=256).contains(&row_count));
    assert!((1..=100000).contains(&read_cap));
    assert!(
        (attempts + 1)
            .checked_mul(row_count)
            .expect("payload size overflow")
            <= 32768
    );
    let payloads = Payloads::new(attempts, row_count);
    let (db, policy) = paths::open(&args[1])?;
    assert_eq!(policy.journal, "wal", "mixed experiment requires WAL");
    let mut query = Some(db.prepare("SELECT id,epoch,payload FROM items ORDER BY id")?);
    let mut output = Vec::with_capacity(128);
    if role == "reader" {
        assert_eq!(begin(&db, "BEGIN DEFERRED")?, 0);
        assert_eq!(scan(query.as_mut().unwrap(), &payloads, &mut output)?, 0);
        control(&db, "COMMIT", "prime-read-commit")?;
    }
    let mut update_statement = if role == "writer" {
        Some(db.prepare("UPDATE items SET epoch=?1,payload=?2 WHERE id=?3")?)
    } else {
        None
    };
    if let Some(statement) = update_statement.as_mut() {
        assert_eq!(begin(&db, "BEGIN IMMEDIATE")?, 0);
        update(statement, 0, &payloads)?;
        control(&db, "ROLLBACK", "prime-rollback")?;
        for end in ["COMMIT", "ROLLBACK"] {
            assert_eq!(begin(&db, "BEGIN IMMEDIATE")?, 0);
            control(&db, end, "prime-empty-control")?;
        }
        query.take().unwrap().finalize()?;
    }
    assert!(db.is_autocommit());
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut input = stdin.lock();
    let mut out = stdout.lock();
    event(
        &mut out,
        format!(
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
        ),
    )?;
    event(&mut out, format!("READY {role}"))?;
    match (role, phase) {
        ("writer", "qualify") => qualify_writer(
            &db,
            update_statement.as_mut().unwrap(),
            &payloads,
            &mut input,
            &mut out,
        )?,
        ("reader", "qualify") => qualify_reader(
            &db,
            query.as_mut().unwrap(),
            &payloads,
            &mut output,
            &mut input,
            &mut out,
        )?,
        ("writer", "mixed") => mixed_writer(
            &db,
            update_statement.as_mut().unwrap(),
            &payloads,
            &mut input,
            &mut out,
        )?,
        ("reader", "mixed") => mixed_reader(
            &db,
            query.as_mut().unwrap(),
            &payloads,
            read_cap,
            &mut output,
            &mut input,
            &mut out,
        )?,
        _ => unreachable!(),
    }
    assert!(db.is_autocommit());
    if let Some(statement) = query.take() {
        statement.finalize()?;
    }
    if let Some(statement) = update_statement.take() {
        statement.finalize()?;
    }
    drop(query);
    drop(update_statement);
    db.close().map_err(|(_, error)| error)?;
    event(&mut out, format!("END {role}"))?;
    Ok(())
}
