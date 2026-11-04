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
static void blob_materialization_faults(sqlite3_int64 baseline) {
    for (int mode = 0; mode < 3; ++mode) {
        int failures = 0, successes = 0;
        for (int n = 0; n < 8; ++n) {
            uint64_t db = open_db(), stmt = 0;
            /* Keep materialization out of constant-expression setup in step(). */
            assert(gq_prepare(db, text("SELECT zeroblob((random() & 0) + 4096)"), &stmt) == SQLITE_OK);
            assert(gq_step(stmt) == SQLITE_ROW);
            uint8_t output[4096]; memset(output, 17, sizeof output);
            int64_t length = 123;
            countdown = n;
            int64_t rc = mode == 0 ? gq_size(stmt, 0, SQLITE_BLOB, &length) :
                mode == 1 ? gq_fetch(stmt, 0, SQLITE_BLOB, (gq_output){output, sizeof output}, &length) :
                            gq_copy(stmt, 0, SQLITE_BLOB, (gq_output){output, sizeof output});
            countdown = -1;
            if (rc == SQLITE_OK) {
                if (mode != 2 && length != sizeof output)
                    fprintf(stderr, "BLOB materialization mode=%d cut=%d code=%lld length=%lld\n", mode, n, (long long)rc, (long long)length);
                assert(mode == 2 || length == sizeof output);
                for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == (mode == 0 ? 17 : 0));
                ++successes;
            } else {
                assert(nomem(rc) && (mode == 2 || length == 0));
                for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 17);
                ++failures;
            }
            int64_t final = gq_finalize(stmt); assert(final == SQLITE_OK || nomem(final));
            assert(gq_close(db) == SQLITE_OK && sqlite3_memory_used() == baseline);
        }
        assert(failures > 0 && successes > 0);
        printf("sqlite BLOB materialization mode=%d failures=%d\n", mode, failures);
    }
    for (int mode = 0; mode < 3; ++mode) {
        uint64_t db = open_db(), stmt = 0;
        assert(gq_prepare(db, text("SELECT zeroblob((random() & 0) + 0)"), &stmt) == SQLITE_OK);
        assert(gq_step(stmt) == SQLITE_ROW);
        uint8_t output = 17; int64_t length = 123;
        countdown = 0;
        int64_t rc = mode == 0 ? gq_size(stmt, 0, SQLITE_BLOB, &length) :
            mode == 1 ? gq_fetch(stmt, 0, SQLITE_BLOB, (gq_output){&output, 1}, &length) :
                        gq_copy(stmt, 0, SQLITE_BLOB, (gq_output){&output, 1});
        countdown = -1;
        assert(rc == SQLITE_OK && (mode == 2 || length == 0) && output == 17);
        assert(gq_type(stmt, 0) == SQLITE_BLOB);
        assert(gq_step(stmt) == SQLITE_DONE && gq_finalize(stmt) == SQLITE_OK);
        assert(gq_close(db) == SQLITE_OK && sqlite3_memory_used() == baseline);
    }
    /* A failed conversion on one statement must not corrupt empty BLOB reads
       from a different live statement on the same connection. */
    uint64_t db = open_db(), empty = 0, failing = 0;
    assert(gq_prepare(db, text("SELECT x'', zeroblob(0), ''"), &empty) == SQLITE_OK);
    assert(gq_step(empty) == SQLITE_ROW);
    assert(gq_prepare(db, text("SELECT zeroblob((random() & 0) + 4096)"), &failing) == SQLITE_OK);
    assert(gq_step(failing) == SQLITE_ROW);
    int64_t length = 123;
    countdown = 0;
    int64_t rc = gq_size(failing, 0, SQLITE_BLOB, &length);
    countdown = -1;
    assert(nomem(rc) && length == 0);
    for (int col = 0; col < 3; ++col) {
        int kind = col == 2 ? SQLITE_TEXT : SQLITE_BLOB;
        length = 123;
        assert(gq_fetch(empty, col, kind, (gq_output){NULL, 0}, &length) == SQLITE_OK && length == 0);
    }
    rc = gq_finalize(failing); assert(rc == SQLITE_OK || nomem(rc));
    assert(gq_finalize(empty) == SQLITE_OK && gq_close(db) == SQLITE_OK);
    assert(sqlite3_memory_used() == baseline);
}
int main(void) {
    assert(sqlite3_config(SQLITE_CONFIG_GETMALLOC, &original) == SQLITE_OK);
    sqlite3_mem_methods hooks = original;
    hooks.xMalloc = allocate; hooks.xRealloc = reallocate;
    assert(sqlite3_config(SQLITE_CONFIG_MALLOC, &hooks) == SQLITE_OK);
    assert(sqlite3_config(SQLITE_CONFIG_MEMSTATUS, 1) == SQLITE_OK);
    /* Disable lookaside so internal BLOB allocations reach the injected allocator. */
    assert(sqlite3_config(SQLITE_CONFIG_LOOKASIDE, 0, 0) == SQLITE_OK);
    /* A failure must not poison later startup. Retry before any shutdown. */
    int init_failures = 0;
    for (int n = 0; n < 32; ++n) {
        countdown = n;
        int64_t rc = gq_initialize();
        countdown = -1;
        if (rc != SQLITE_OK) { assert(nomem(rc)); ++init_failures; }
        assert(gq_initialize() == SQLITE_OK && gq_initialize() == SQLITE_OK);
        uint64_t db = open_db();
        assert(gq_close(db) == SQLITE_OK);
        assert(sqlite3_shutdown() == SQLITE_OK && sqlite3_memory_used() == 0);
    }
    assert(init_failures > 0);
    printf("sqlite initialization failures recovered: %d\n", init_failures);
    assert(gq_initialize() == SQLITE_OK);
    sqlite3_int64 baseline = sqlite3_memory_used();
    blob_materialization_faults(baseline);
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
    int blob_failures = 0, backup_failures = 0;
    for (int n = 0; n < 128; ++n) {
        uint64_t db = open_db(), stmt = 0, blob = 123;
        assert(gq_prepare(db,text("CREATE TABLE t(x)"),&stmt) == SQLITE_OK);
        assert(gq_step(stmt) == SQLITE_DONE && gq_finalize(stmt) == SQLITE_OK);
        assert(gq_prepare(db,text("INSERT INTO t VALUES(zeroblob(4096))"),&stmt) == SQLITE_OK);
        assert(gq_step(stmt) == SQLITE_DONE && gq_finalize(stmt) == SQLITE_OK);
        countdown = n;
        int64_t rc = gq_blob_open(db,text("t"),text("x"),1,0,&blob);
        countdown = -1;
        if (rc == SQLITE_OK) assert(blob && gq_blob_close(blob) == SQLITE_OK);
        else { assert(nomem(rc) && blob == 0); ++blob_failures; }
        assert(gq_close(db) == SQLITE_OK && sqlite3_memory_used() == baseline);
    }
    for (int n = 0; n < 128; ++n) {
        uint64_t src = open_db(), dst = open_db(), stmt = 0;
        assert(gq_prepare(src,text("CREATE TABLE t(x)"),&stmt) == SQLITE_OK);
        assert(gq_step(stmt) == SQLITE_DONE && gq_finalize(stmt) == SQLITE_OK);
        assert(gq_prepare(src,text("INSERT INTO t VALUES(zeroblob(16384))"),&stmt) == SQLITE_OK);
        assert(gq_step(stmt) == SQLITE_DONE && gq_finalize(stmt) == SQLITE_OK);
        countdown = n;
        int64_t rc = gq_backup(src,dst,100);
        countdown = -1;
        if (rc != SQLITE_OK) { assert(nomem(rc)); ++backup_failures; }
        assert(gq_close(src) == SQLITE_OK && gq_close(dst) == SQLITE_OK);
        assert(sqlite3_memory_used() == baseline);
    }
    assert(blob_failures > 0 && backup_failures > 0);
    printf("sqlite storage allocation failures: blob=%d backup=%d\n",blob_failures,backup_failures);
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
