/* SPDX-License-Identifier: Apache-2.0 */
#define _POSIX_C_SOURCE 200809L
#include "../native/sqlite.h"
#include <sqlite3.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>

/* Separate executable: allocator configuration precedes all SQLite use. */
static sqlite3_mem_methods original;
static int countdown = -1;
static int fail_now(void) {
    if (countdown < 0) return 0;
    return countdown-- == 0;
}
static void *allocate(int n) { return fail_now() ? NULL : original.xMalloc(n); }
static void *reallocate(void *p, int n) { return fail_now() ? NULL : original.xRealloc(p, n); }
static gq_input text(const char *s) { return (gq_input){(const uint8_t *)s, (int64_t)strlen(s)}; }
static uint64_t open_db(void) {
    uint64_t db = 0; assert(gq_open(text(":memory:"), 0, 0, 1000000, &db) == SQLITE_OK); return db;
}
static int nomem(int64_t rc) { return rc > 0 && (rc & 255) == SQLITE_NOMEM; }
int main(void) {
    assert(sqlite3_config(SQLITE_CONFIG_GETMALLOC, &original) == SQLITE_OK);
    sqlite3_mem_methods hooks = original;
    hooks.xMalloc = allocate; hooks.xRealloc = reallocate;
    assert(sqlite3_config(SQLITE_CONFIG_MALLOC, &hooks) == SQLITE_OK);
    assert(sqlite3_config(SQLITE_CONFIG_MEMSTATUS, 1) == SQLITE_OK);
    assert(sqlite3_initialize() == SQLITE_OK);
    sqlite3_int64 baseline = sqlite3_memory_used();
    int open_failures = 0, prepare_failures = 0, bind_failures = 0, step_failures = 0;
    for (int n = 0; n < 256; ++n) {
        uint64_t db = 123;
        countdown = n;
        int64_t rc = gq_open(text(":memory:"), 0, 0, 1000000, &db);
        countdown = -1;
        if (rc == SQLITE_OK) { assert(db != 0); assert(gq_close(db) == SQLITE_OK); }
        else { assert(nomem(rc) && db == 0); ++open_failures; }
        assert(sqlite3_memory_used() == baseline);
    }
    for (int n = 0; n < 256; ++n) {
        uint64_t db = open_db(), stmt = 123;
        countdown = n;
        int64_t rc = gq_prepare(db, text("SELECT ?1, ?2, CAST(?3 AS TEXT), randomblob(4096)"), &stmt);
        countdown = -1;
        if (rc == SQLITE_OK) { assert(stmt != 0); assert(gq_finalize(stmt) == SQLITE_OK); }
        else { assert(nomem(rc) && stmt == 0); ++prepare_failures; }
        assert(gq_close(db) == SQLITE_OK);
        assert(sqlite3_memory_used() == baseline);
    }
    uint8_t bytes[4096]; memset(bytes, 'x', sizeof bytes);
    for (int n = 0; n < 64; ++n) {
        uint64_t db = open_db(), stmt = 0;
        assert(gq_prepare(db, text("SELECT ?1"), &stmt) == SQLITE_OK);
        countdown = n;
        int64_t rc = gq_bind(stmt, 1, SQLITE_TEXT, 0, 0, (gq_input){bytes, sizeof bytes});
        countdown = -1;
        if (rc != SQLITE_OK) { assert(nomem(rc)); ++bind_failures; }
        assert(gq_finalize(stmt) == SQLITE_OK);
        assert(gq_close(db) == SQLITE_OK);
        assert(sqlite3_memory_used() == baseline);
    }
    for (int n = 0; n < 64; ++n) {
        uint64_t db = open_db(), stmt = 0;
        assert(gq_prepare(db, text("SELECT randomblob(4096), printf('%s%s', ?1, ?1)"), &stmt) == SQLITE_OK);
        assert(gq_bind(stmt, 1, SQLITE_TEXT, 0, 0, (gq_input){bytes, sizeof bytes}) == SQLITE_OK);
        countdown = n;
        int64_t rc = gq_step(stmt);
        countdown = -1;
        if (rc == SQLITE_ROW) {
            int64_t size = 0;
            assert(gq_size(stmt, 0, SQLITE_BLOB, &size) == SQLITE_OK && size == sizeof bytes);
        } else { assert(nomem(rc)); ++step_failures; }
        int64_t finalized = gq_finalize(stmt);
        assert(finalized == SQLITE_OK || nomem(finalized));
        assert(gq_finalize(stmt) == GQ_HANDLE);
        assert(gq_close(db) == SQLITE_OK);
        assert(sqlite3_memory_used() == baseline);
    }
    /* Force a stored UTF-16 TEXT -> UTF-8 conversion in the byte getter. */
    char path[] = "/tmp/goose-sqlite-encoding-XXXXXX";
    int fd = mkstemp(path); assert(fd >= 0); assert(close(fd) == 0);
    sqlite3 *fixture = NULL;
    assert(sqlite3_open(path, &fixture) == SQLITE_OK);
    assert(sqlite3_exec(fixture, "PRAGMA encoding='UTF-16le'; CREATE TABLE t(x); INSERT INTO t VALUES(printf('%1024s','x'));", NULL,NULL,NULL) == SQLITE_OK);
    assert(sqlite3_close(fixture) == SQLITE_OK);
    int conversion_failures = 0;
    for (int n = 0; n < 16; ++n) {
        uint64_t db = 0, stmt = 0;
        assert(gq_open(text(path),0,0,1000000,&db) == SQLITE_OK);
        assert(gq_prepare(db,text("SELECT x FROM t"),&stmt) == SQLITE_OK);
        assert(gq_step(stmt) == SQLITE_ROW);
        uint8_t output[1024]; memset(output,17,sizeof output);
        int64_t length = -1;
        countdown = n;
        int64_t rc = gq_fetch(stmt,0,SQLITE_TEXT,(gq_output){output,sizeof output},&length);
        countdown = -1;
        if (rc == SQLITE_OK) { assert(length == 1024 && output[1023] == 'x'); }
        else { assert(nomem(rc) && length == 0 && output[0] == 17); ++conversion_failures; }
        int64_t final = gq_finalize(stmt); assert(final == SQLITE_OK || nomem(final));
        assert(gq_close(db) == SQLITE_OK);
        assert(sqlite3_memory_used() == baseline);
    }
    assert(unlink(path) == 0 && conversion_failures > 0);
    assert(open_failures > 0 && prepare_failures > 0 && bind_failures > 0 && step_failures > 0);
    printf("sqlite allocation-failure tests passed: open=%d prepare=%d bind=%d step=%d conversion=%d\n",
           open_failures, prepare_failures, bind_failures, step_failures, conversion_failures);
    return 0;
}
