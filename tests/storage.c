/* SPDX-License-Identifier: Apache-2.0 */
#define _POSIX_C_SOURCE 200809L
#include "../native/sqlite.h"
#include <sqlite3.h>
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static gq_input text(const char *s) { return (gq_input){(const uint8_t *)s, (int64_t)strlen(s)}; }
static uint64_t open_db(const char *p) {
    uint64_t d = 0; assert(gq_open(text(p), 0, 0, 1000000, &d) == SQLITE_OK); return d;
}
static uint64_t prepare(uint64_t d, const char *sql) {
    uint64_t s = 0; assert(gq_prepare(d, text(sql), &s) == SQLITE_OK); return s;
}
static int64_t exec(uint64_t d, const char *sql) {
    uint64_t s = 0; int64_t rc = gq_prepare(d, text(sql), &s);
    if (rc) return rc;
    rc = gq_step(s); int64_t closed = gq_finalize(s);
    return rc == SQLITE_DONE ? closed : rc;
}
static int64_t scalar(uint64_t d, const char *sql) {
    uint64_t s = prepare(d, sql); int64_t out = 0;
    assert(gq_step(s) == SQLITE_ROW && gq_integer(s, 0, &out) == SQLITE_OK);
    assert(gq_finalize(s) == SQLITE_OK); return out;
}
static uint64_t open_blob(uint64_t d, int writable) {
    uint64_t b = 0; assert(gq_blob_open(d, text("t"), text("x"), -7, writable, &b) == SQLITE_OK); return b;
}
static int aborted(int64_t rc) { return rc > 0 && (rc & 255) == SQLITE_ABORT; }
static void *foreign(void *p) {
    uint64_t b = *(uint64_t *)p; int64_t size = 123;
    assert(gq_blob_size(b, &size) == GQ_HANDLE && size == 0);
    assert(gq_blob_close(b) == GQ_HANDLE);
    assert(gq_blob_read(b, 0, (gq_output){NULL,0}) == GQ_HANDLE);
    return NULL;
}
static void *abandon(void *p) {
    uint64_t d = open_db(p);
    assert(exec(d, "BEGIN") == SQLITE_OK);
    uint64_t b = open_blob(d, 1);
    assert(gq_blob_write(b, 0, text("x")) == SQLITE_OK);
    return NULL; /* Close blob then rollback explicit write at thread exit. */
}
static int fixed(void) {
    int n = sqlite3_libversion_number();
    return n >= 3051003 || (n >= 3050007 && n < 3051000) || (n >= 3044006 && n < 3045000);
}
/* Test-only auto-extension captures the engine connection for post-open inspection.
   This does not add any production pointer or authorizer escape API. */
static sqlite3 *captured;
static int initial_sync;
static int capture(sqlite3 *db, char **error, const sqlite3_api_routines *api) {
    (void)error; (void)api;
    captured = db;
    return sqlite3_exec(db, initial_sync == 3 ? "PRAGMA synchronous=EXTRA" :
        "PRAGMA synchronous=OFF", NULL,NULL,NULL);
}
static void check_sync(const char *path, int before, int expected) {
    initial_sync = before; captured = NULL;
    assert(sqlite3_auto_extension((void (*)(void))capture) == SQLITE_OK);
    uint64_t d = 0;
    assert(gq_open_config(text(path),0,0,1000000,1,&d) == SQLITE_OK && captured);
    sqlite3_reset_auto_extension();
    assert(exec(d,"PRAGMA synchronous") == SQLITE_AUTH);
    /* Inspect ONLY after checking that public SQL cannot bypass authorization. */
    assert(sqlite3_set_authorizer(captured,NULL,NULL) == SQLITE_OK);
    sqlite3_stmt *s = NULL;
    assert(sqlite3_prepare_v2(captured,"PRAGMA main.synchronous",-1,&s,NULL) == SQLITE_OK);
    assert(sqlite3_step(s) == SQLITE_ROW && sqlite3_column_int(s,0) == expected);
    assert(sqlite3_finalize(s) == SQLITE_OK && gq_close(d) == SQLITE_OK);
    captured = NULL;
}
int main(void) {
    uint64_t d = open_db(":memory:");
    assert(exec(d, "CREATE TABLE t(id INTEGER PRIMARY KEY, x BLOB, y)") == SQLITE_OK);
    assert(exec(d, "INSERT INTO t VALUES(-7, zeroblob(8192), 0)") == SQLITE_OK);
    uint64_t b = 1;
    assert(gq_blob_open(d,text("t"),text("x"),-7,1,&b) == GQ_STATE && b == 0);
    assert(exec(d,"BEGIN") == SQLITE_OK);
    b = open_blob(d,1);
    uint8_t unaligned[10] = {0}; int64_t size;
    assert(gq_blob_size(b,unaligned+1) == SQLITE_OK);
    memcpy(&size,unaligned+1,8); assert(size == 8192);
    assert(gq_blob_write(b,8190,text("ab")) == SQLITE_OK);
    assert(gq_blob_write(b,INT64_MAX,text("ab")) == GQ_INPUT);
    assert(gq_blob_write(b,-1,text("")) == GQ_INPUT);
    assert(gq_blob_write(b,8191,text("ab")) == GQ_INPUT);
    assert(gq_blob_write(b,0,(gq_input){NULL,1}) == GQ_INPUT);
    uint8_t bytes[6] = {17,18,19,20,21,22};
    assert(gq_blob_read(b,8190,(gq_output){bytes+1,2}) == SQLITE_OK);
    assert(bytes[0] == 17 && bytes[1] == 'a' && bytes[2] == 'b' && bytes[3] == 20);
    assert(gq_blob_read(b,0,(gq_output){bytes,-1}) == GQ_INPUT);
    assert(gq_blob_read(b,0,(gq_output){NULL,1}) == GQ_INPUT);
    assert(gq_blob_read(b,8192,(gq_output){NULL,0}) == SQLITE_OK);
    assert(gq_close(d) == SQLITE_BUSY && exec(d,"COMMIT") == SQLITE_BUSY);
    pthread_t worker;
    assert(!pthread_create(&worker,NULL,foreign,&b) && !pthread_join(worker,NULL));
    assert(gq_blob_close(b) == SQLITE_OK && gq_blob_close(b) == GQ_HANDLE);
    assert(exec(d,"COMMIT") == SQLITE_OK);
    b = open_blob(d,0);
    assert(gq_blob_write(b,0,text("")) == SQLITE_READONLY);
    assert(exec(d,"UPDATE t SET y=1") == SQLITE_OK);
    assert(aborted(gq_blob_read(b,0,(gq_output){bytes,1})));
    assert(aborted(gq_blob_read(b,0,(gq_output){NULL,0})));
    assert(aborted(gq_blob_size(b,&size)) && size == 0);
    int64_t closed = gq_blob_close(b); assert(closed == SQLITE_OK || aborted(closed));
    assert(exec(d,"BEGIN") == SQLITE_OK);
    b = open_blob(d,1);
    assert(exec(d,"ROLLBACK") == SQLITE_OK);
    assert(aborted(gq_blob_size(b,&size)) && size == 0);
    assert(aborted(gq_blob_write(b,0,text(""))));
    assert(aborted(gq_blob_close(b)) && gq_blob_close(b) == GQ_HANDLE);
    assert(exec(d,"INSERT INTO t VALUES(1, zeroblob(0),0)") == SQLITE_OK);
    assert(gq_blob_open(d,text("t"),text("x"),1,0,&b) == SQLITE_OK);
    assert(gq_blob_size(b,&size) == SQLITE_OK && size == 0);
    assert(gq_blob_read(b,0,(gq_output){NULL,0}) == SQLITE_OK && gq_blob_close(b) == SQLITE_OK);
    assert(gq_blob_open(d,text("t\0bad"),text("x"),1,0,&b) == SQLITE_OK); /* text helper stops at NUL. */
    assert(gq_blob_close(b) == SQLITE_OK);
    assert(gq_blob_open(d,(gq_input){(const uint8_t *)"t\0bad",5},text("x"),1,0,&b) == GQ_INPUT && b == 0);
    assert(gq_blob_open(d,text("t"),text("x"),999,0,&b) > 0 && b == 0);
    /* Capacity and stale generations, across all BLOB slots. */
    uint64_t blobs[32]; for (int i=0;i<32;++i) blobs[i]=open_blob(d,0);
    assert(gq_blob_open(d,text("t"),text("x"),-7,0,&b) == GQ_LIMIT && b == 0);
    uint64_t stale = blobs[0];
    for (int i=0;i<32;++i) assert(gq_blob_close(blobs[i]) == SQLITE_OK);
    b = open_blob(d,0); assert(b != stale && gq_blob_close(stale) == GQ_HANDLE);
    assert(gq_blob_close(b) == SQLITE_OK);
    /* Engine restrictions and explicitly documented CHECK/trigger bypass. */
    assert(exec(d,"CREATE TABLE generated(x BLOB, y AS (length(x)))") == SQLITE_OK);
    assert(exec(d,"INSERT INTO generated(x) VALUES(zeroblob(4))") == SQLITE_OK);
    /* Older supported engines permit ordinary columns in generated-column tables. */
    int64_t generated = gq_blob_open(d,text("generated"),text("x"),1,0,&b);
    if (generated == SQLITE_OK) assert(b && gq_blob_close(b) == SQLITE_OK);
    else assert(generated > 0 && b == 0);
    assert(exec(d,"CREATE TABLE checked(x BLOB CHECK(hex(x)='6162'))") == SQLITE_OK);
    assert(exec(d,"INSERT INTO checked VALUES(x'6162')") == SQLITE_OK);
    assert(exec(d,"CREATE TABLE log(x)") == SQLITE_OK);
    assert(exec(d,"CREATE TRIGGER audit AFTER UPDATE ON checked BEGIN INSERT INTO log VALUES(1); END") == SQLITE_OK);
    assert(exec(d,"BEGIN") == SQLITE_OK);
    assert(gq_blob_open(d,text("checked"),text("x"),1,1,&b) == SQLITE_OK);
    assert(gq_blob_write(b,0,text("zz")) == SQLITE_OK && gq_blob_close(b) == SQLITE_OK);
    assert(exec(d,"COMMIT") == SQLITE_OK && scalar(d,"SELECT count(*) FROM log") == 0);
    assert(scalar(d,"SELECT x=x'7a7a' FROM checked") == 1);
    assert(exec(d,"CREATE INDEX idx ON checked(x)") == SQLITE_OK);
    assert(exec(d,"BEGIN") == SQLITE_OK);
    assert(gq_blob_open(d,text("checked"),text("x"),1,1,&b) > 0 && b == 0);
    assert(exec(d,"ROLLBACK") == SQLITE_OK);
    uint64_t dst = open_db(":memory:");
    assert(exec(dst,"CREATE TABLE old(x)") == SQLITE_OK && exec(dst,"INSERT INTO old VALUES(42)") == SQLITE_OK);
    assert(gq_backup(d,dst,1) == GQ_LIMIT && scalar(dst,"SELECT x FROM old") == 42);
    uint64_t s = prepare(dst,"SELECT 1");
    assert(gq_backup(d,dst,100) == GQ_STATE && gq_finalize(s) == SQLITE_OK);
    assert(gq_backup(d,dst,0) == GQ_INPUT && gq_backup(d,dst,1048577) == GQ_INPUT);
    assert(gq_backup(d,d,100) == GQ_INPUT);
    assert(exec(d,"BEGIN IMMEDIATE") == SQLITE_OK && gq_backup(d,dst,100) == GQ_STATE);
    assert(exec(d,"ROLLBACK") == SQLITE_OK);
    assert(exec(d,"BEGIN") == SQLITE_OK);
    s = prepare(d,"SELECT x FROM t"); assert(gq_step(s) == SQLITE_ROW);
    assert(gq_backup(d,dst,100) == SQLITE_OK && scalar(dst,"SELECT y FROM t WHERE id=-7") == 1);
    assert(gq_finalize(s) == SQLITE_OK && exec(d,"COMMIT") == SQLITE_OK);
    assert(exec(dst,"BEGIN") == SQLITE_OK && gq_backup(d,dst,100) == GQ_STATE);
    assert(exec(dst,"ROLLBACK") == SQLITE_OK);
    assert(gq_close(dst) == SQLITE_OK && gq_close(d) == SQLITE_OK);
    /* Isolated file, WAL and busy backup behavior. */
    char dir[] = "/tmp/goose-sqlite-storage-XXXXXX"; assert(mkdtemp(dir));
    char path[256], target[256], sidecar[264];
    assert(snprintf(path,sizeof path,"%s/source.db",dir)>0);
    assert(snprintf(target,sizeof target,"%s/target.db",dir)>0);
    d = open_db(path);
    assert(exec(d,"CREATE TABLE t(id INTEGER PRIMARY KEY,x,y)") == SQLITE_OK);
    assert(exec(d,"INSERT INTO t VALUES(-7,zeroblob(8192),0)") == SQLITE_OK);
    assert(!pthread_create(&worker,NULL,abandon,path) && !pthread_join(worker,NULL));
    assert(scalar(d,"SELECT hex(substr(x,1,1))='00' FROM t") == 1);
    dst = open_db(target); uint64_t lock = open_db(target);
    assert(exec(dst,"CREATE TABLE old(x)") == SQLITE_OK && exec(dst,"INSERT INTO old VALUES(42)") == SQLITE_OK);
    assert(exec(lock,"BEGIN EXCLUSIVE") == SQLITE_OK);
    assert(gq_backup(d,dst,100) == SQLITE_BUSY);
    assert(exec(lock,"ROLLBACK") == SQLITE_OK && scalar(dst,"SELECT x FROM old") == 42);
    assert(gq_backup(d,dst,100) == SQLITE_OK);
    assert(gq_close(lock) == SQLITE_OK && gq_close(dst) == SQLITE_OK);
    uint64_t ro = 0; assert(gq_open(text(target),1,0,1000000,&ro) == SQLITE_OK);
    assert(gq_backup(d,ro,100) == SQLITE_READONLY && gq_close(ro) == SQLITE_OK);
    assert(gq_close(d) == SQLITE_OK);
    uint64_t wal = 123;
    assert(gq_open_config(text(path),1,0,1000000,1,&wal) == GQ_INPUT && wal == 0);
    int64_t wrc = gq_open_config(text(path),0,0,1000000,1,&wal);
    if (fixed()) {
        assert(wrc == SQLITE_OK && wal);
        d = open_db(path); assert(exec(d,"BEGIN") == SQLITE_OK);
        assert(scalar(d,"SELECT y FROM t") == 0);
        assert(exec(wal,"UPDATE t SET y=1") == SQLITE_OK);
        assert(scalar(d,"SELECT y FROM t") == 0); /* Old reader snapshot survives writer commit. */
        assert(exec(d,"COMMIT") == SQLITE_OK && scalar(d,"SELECT y FROM t") == 1);
        assert(exec(wal,"PRAGMA journal_mode") == SQLITE_AUTH);
        assert(gq_close(d) == SQLITE_OK && gq_close(wal) == SQLITE_OK);
        assert(gq_open_config(text(":memory:"),0,0,1000000,1,&wal) == SQLITE_ERROR && wal == 0);
    } else {
        assert(wrc == SQLITE_MISUSE && wal == 0);
        sqlite3 *raw = NULL; assert(sqlite3_open(path,&raw) == SQLITE_OK);
        assert(sqlite3_exec(raw,"PRAGMA journal_mode=WAL",NULL,NULL,NULL) == SQLITE_OK);
        assert(sqlite3_close(raw) == SQLITE_OK);
        assert(gq_open(text(path),0,0,1000000,&wal) == SQLITE_MISUSE && wal == 0);
    }
    if (fixed()) {
        check_sync(path,0,2); /* OFF is raised to FULL. */
        check_sync(path,3,3); /* EXTRA survives WAL initialization. */
    }
    /* Page-size mismatch cannot overwrite an existing in-memory destination. */
    char large_path[256]; snprintf(large_path,sizeof large_path,"%s/large.db",dir);
    sqlite3 *large = NULL; assert(sqlite3_open(large_path,&large) == SQLITE_OK);
    assert(sqlite3_exec(large,"PRAGMA page_size=8192; CREATE TABLE t(x); INSERT INTO t VALUES(zeroblob(10000))",NULL,NULL,NULL) == SQLITE_OK);
    assert(sqlite3_close(large) == SQLITE_OK);
    uint64_t source_large = open_db(large_path), small = open_db(":memory:");
    assert(exec(small,"CREATE TABLE old(x)") == SQLITE_OK && exec(small,"INSERT INTO old VALUES(42)") == SQLITE_OK);
    assert((gq_backup(source_large,small,100) & 255) == SQLITE_READONLY);
    assert(scalar(small,"SELECT x FROM old") == 42 && gq_close(small) == SQLITE_OK);
    if (fixed()) {
        assert(gq_open_config(text(target),0,0,1000000,1,&small) == SQLITE_OK);
        assert(exec(small,"CREATE TABLE old(x)") == SQLITE_OK && exec(small,"INSERT INTO old VALUES(42)") == SQLITE_OK);
        assert((gq_backup(source_large,small,100) & 255) == SQLITE_READONLY);
        assert(scalar(small,"SELECT x FROM old") == 42 && gq_close(small) == SQLITE_OK);
    }
    assert(gq_close(source_large) == SQLITE_OK && unlink(large_path) == 0);
    assert(unlink(path) == 0 && unlink(target) == 0);
    snprintf(sidecar,sizeof sidecar,"%s-wal",path); unlink(sidecar);
    snprintf(sidecar,sizeof sidecar,"%s-shm",path); unlink(sidecar);
    assert(rmdir(dir) == 0);
    puts("sqlite storage native tests passed");
    return 0;
}
