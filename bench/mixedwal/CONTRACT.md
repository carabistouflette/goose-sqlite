# Coordinated finite WAL reader/writer contract

One reader + one writer PROCESS of the same implementation, distinct connections.
CLI: runner PATH ROLE PHASE ATTEMPTS ROWS READ_CAP; ROLE reader/writer;
PHASE qualify/mixed. attempts8..4096, rows1..256, read_cap1..100000,
(attempts+1)*rows<=32768. Defaults128 attempts,32rows,20000reader cap.
Policies and open flags match filebacked CONTRACT, WAL ONLY; busy0, FULL2,
cache-2000, normal locking, auto-checkpoint1000, FK1, trusted_schema0.
Goose options wal=false discover preseeded WAL; two-role settings inferred from
exact-archive native probe; other runners read back their actual connection.
No public library changes or C IPC helper. stdin/out flushed line protocol.

Schema items(id INTEGER PRIMARY KEY,epoch INTEGER NOT NULL,payload BLOB NOT NULL).
Initial IDs0..ROWS-1 epoch0. Payload128bytes, byte0=0,last=255; middle byte j:
(epoch*17+id*31+j*7)%256. Precompute all valid epoch/id expected payloads BEFORE
READY (epochs0..max(attempts,2)), outside clocks. Bound allocation as above.
Reader priming is BEGIN DEFERRED/full epoch0 scan/COMMIT.
Reader SELECT id,epoch,payload FROM items ORDER BY id, consumes every row/DONE,
strict types and copied owned bytes, verifies exact IDs, one common epoch and all
payload bytes. Epoch must be0..attempts; successful reader epochs never decrease.
Writer prepared UPDATE items SET epoch=?1,payload=?2 WHERE id=?3, each row changes1.
Normal cached/prepared control SQL differences remain disclosed. Prime SELECT
and writer one UPDATE-all epoch0 in rolled-back transaction followed by empty BEGIN IMMEDIATE/COMMIT and BEGIN IMMEDIATE/ROLLBACK before READY; do not
change logical seed. Finish all priming cursors. Every process opens once.

First stdout line `policy ...` exactly filebacked format or `policy inferred`
forGoose, then `READY ROLE`, flush. Commands stdin single lines. EOF before a required token or malformed
command is a failed run; language line readers may accept a final unterminated
one-token line, so strict newline framing is not claimed; parent owns timeout/child groups and drains both pipes.

Qualification (no performance conclusions):
reader H -> BEGIN, full epoch0 scan, keep explicit txn, reply HELD 0.
writer C -> BEGIN IMMEDIATE, update all epoch1, COMMIT, reply COMMITTED 1.
reader V -> scan held txn mustepoch0, reply VERIFIED 0.
reader F -> end held txn, fresh BEGIN/fullscan epoch1/COMMIT, reply FRESH 1.
writer U -> BEGIN IMMEDIATE, update all epoch2, keep uncommitted, reply DIRTY 2.
reader F -> fresh transaction fullscan mustepoch1, reply FRESH 1.
writer B -> ROLLBACK, reply ROLLED_BACK 2.
reader F -> fresh fullscan mustepoch1, reply FRESH 1.
S toboth -> clean statements/close, reply END ROLE. Parent verifies finalepoch1
allrows/payload/integrity. Qualification separate files from measured pairs.

Mixed:
Parent sends G toboth after READY. Each emits START ROLE (flush) before own clock.
Writer fixed ATTEMPTS iterations, no application retries. Start per-op clock;
BEGIN IMMEDIATE. If BEGIN returns BUSY(primary5), require autocommittrue, leave
published epoch unchanged. Otherwise update all rows to successful_commits+1,
COMMIT, increment epoch only after success. Any update/commit error invalidates
pair with diagnostic actual stage/code; never turn unexpected errors into BUSY.
End clock after changes/reset/control checks. Emit/flush after each attempt:
W index latency_ns actual_code published_epoch (index1-based).
Writer whole-window includes event formatting/flushing/bookkeeping, excludes
START and DONE emission. On finishing emit DONE writer window_ns commits busy
then cleanup/finalize/close and END writer. Post-DONE failure still fails pair.

Reader after G performs one checked read transaction: clock BEGIN DEFERRED,
full scan/copy/verification, COMMIT. BEGIN BUSY requires autocommittrue and epoch=-1;
other failures invalidate pair. End clock; emit/flush R index latency_ns code epoch.
Then wait command N or S OUTSIDE transaction clock. N starts next attempt; S stops.
Reader whole-window includes event formatting/flushing and coordinator wait.
On S emit DONE reader window_ns successes busy then clean close and END reader.
Reaching READ_CAP while parent still needs work is a workload-gate failure.
No per-role buffered result dump; parent flushes all W/R events individually.

Parent after each R sends N until writer DONE observed, then S; at most one
reader command in flight. Count BEGIN BUSY attempts distinctly; verify code>=0
and primary5, successful code0. No BUSY is required with a single WAL writer.
Parent keeps an idle initialized WAL anchor connection to avoid last-close work
until both processes finish. Record pre/post WAL files before anchor cleanup.
Independent reopen/full-data/integrity oracle: final epoch=writer commits, IDs
and every payload exact. Verify every successful reader epoch belongs0..commits.

Principal gates declared before recording: >=max(8,ceil(.75*ATTEMPTS)) writer
commits, every W and R observed, both clean END/exits, no unexpected error, cap/
120second deadline not reached. Reader observes all4 intermediate progress bands:
for each successful observed e with1<=e<final_commits, band=floor((e-1)*4/(final_commits-1)).
Require bands{0,1,2,3}. Failure retained, no selective rerun. Small --smoke records
coverage but skips this performance coverage gate; deterministic qualification
is still mandatory. This gate proves useful interleaving, not continuous overlap.

Balanced10rounds/caller,5 each reader/writer CPU orientation, caller order shuffled
perround seed219. Parent/coordinator on third core where possible. Retain topology,
all role/op durations/codes/epochs, READY/G/START/W/R/DONE/N/S/END parent timestamps,
reader stop lag, per-role RSS separately, pair wall and initial/final WAL states.
No cross-language clock subtraction; epochs and parent events establish progress.

Metric names: checked read-transaction latency (includes copying/verification),
writer successful-commit latency, BEGIN-BUSY rejection latency, recorded writer
loop commits/s (includes event logging), COORDINATED reader snapshots/s (includes
per-snapshot IPC wait). These are coupled implementation-pair workloads, NOT
identical offered reader load, isolated writer overhead, free-running saturation,
fairness, retry quality, exact continuous overlap, power-loss or cold-start TSan.
No attribution to checkpoints without separate evidence. Preserve all failures.
