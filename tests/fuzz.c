/* SPDX-License-Identifier: Apache-2.0 */
#include "../native/sqlite.h"
#include <sqlite3.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do { if (!(x)) abort(); } while (0)
/* A small model exercises valid/invalid operation order, not just SQL bytes. */
static void lifecycle(uint64_t db, const uint8_t *data, size_t size) {
    const gq_input sql = {(const uint8_t *)"SELECT ?1", 9};
    uint64_t stmt = 0, stale = 0;
    CHECK(gq_prepare(db, sql, &stmt) == SQLITE_OK);
    int state = 0, kind = SQLITE_NULL; /* Ready, Row, Done. */
    for (size_t i = 0; i < size && i < 64; ++i) {
        int64_t rc, expected = state == 0 ? SQLITE_OK : GQ_STATE;
        switch (data[i] % 16) {
        case 0:
            CHECK(gq_bind(stmt, 1, SQLITE_INTEGER, (int64_t)i, 0, (gq_input){NULL, 0}) == expected);
            if (!state) kind = SQLITE_INTEGER;
            break;
        case 1:
            CHECK(gq_bind(stmt, 1, SQLITE_NULL, 0, 0, (gq_input){NULL, 0}) == expected);
            if (!state) kind = SQLITE_NULL;
            break;
        case 2:
            CHECK(gq_bind(stmt, 1, SQLITE_BLOB, 0, 0, (gq_input){data, (int64_t)size}) == expected);
            if (!state) kind = SQLITE_BLOB;
            break;
        case 3:
            rc = gq_step(stmt);
            CHECK(rc == (state == 0 ? SQLITE_ROW : state == 1 ? SQLITE_DONE : GQ_STATE));
            if (state < 2) ++state;
            break;
        case 4:
            CHECK(gq_reset(stmt) == SQLITE_OK); state = 0;
            break;
        case 5:
            CHECK(gq_clear(stmt) == expected);
            if (!state) kind = SQLITE_NULL;
            break;
        case 6:
            CHECK(gq_type(stmt, 0) == (state == 1 ? kind : GQ_STATE));
            break;
        case 7:
            stale = stmt; CHECK(gq_finalize(stmt) == SQLITE_OK);
            CHECK(gq_prepare(db, sql, &stmt) == SQLITE_OK);
            CHECK(gq_step(stale) == GQ_HANDLE);
            state = 0; kind = SQLITE_NULL;
            break;
        case 8:
            CHECK(gq_type(stmt, 1) == (state == 1 ? GQ_INPUT : GQ_STATE));
            break;
        case 9:
            CHECK(gq_step(stale) == GQ_HANDLE);
            break;
        case 10:
            CHECK(gq_bind(stmt, 1, SQLITE_FLOAT, 0, 1.5, (gq_input){NULL, 0}) == expected);
            if (!state) kind = SQLITE_FLOAT;
            break;
        case 12: CHECK(gq_parameter_count(stmt) == 1); break;
        case 13: CHECK(gq_parameter_index(stmt, (gq_input){(const uint8_t *)"?1",2}) == 1); break;
        case 14: {
            uint8_t name[2]; int64_t n = -1;
            CHECK(gq_name(stmt, 0, (gq_output){name,2}, &n) == SQLITE_OK && n == 2);
            CHECK(name[0] == '?' && name[1] == '1'); break;
        }
        case 15: {
            int64_t value = -1;
            CHECK(gq_status(db, 2, &value) == SQLITE_OK && (value == 0 || value == 1));
            CHECK(gq_stmt_status(stmt, SQLITE_STMTSTATUS_RUN, 0, &value) == SQLITE_OK && value >= 0); break;
        }
        case 11: {
            int64_t length = -1;
            rc = gq_size(stmt, 0, SQLITE_BLOB, &length);
            expected = state != 1 ? GQ_STATE : kind != SQLITE_BLOB ? GQ_TYPE : SQLITE_OK;
            CHECK(rc == expected);
            CHECK(length == (rc == SQLITE_OK ? (int64_t)size : 0));
            break;
        }
        }
    }
    CHECK(gq_finalize(stmt) == SQLITE_OK);
}
static void run_sql(uint64_t db, const char *sql) {
    uint64_t stmt = 0;
    CHECK(gq_prepare(db,(gq_input){(const uint8_t *)sql,(int64_t)strlen(sql)},&stmt) == SQLITE_OK);
    CHECK(gq_step(stmt) == SQLITE_DONE && gq_finalize(stmt) == SQLITE_OK);
}
static void blob_lifecycle(const uint8_t *data, size_t size) {
    uint64_t db = 0, b = 0, stale = 0;
    CHECK(gq_open((gq_input){(const uint8_t *)":memory:",8},0,0,1000000,&db) == SQLITE_OK);
    run_sql(db,"CREATE TABLE t(x)"); run_sql(db,"INSERT INTO t VALUES(zeroblob(256))");
    run_sql(db,"BEGIN");
    const gq_input table = {(const uint8_t *)"t",1}, col = {(const uint8_t *)"x",1};
    CHECK(gq_blob_open(db,table,col,1,1,&b) == SQLITE_OK);
    uint8_t model[256] = {0}, out[256];
    for (size_t i = 0; i < size && i < 32; ++i) {
        int offset = data[i], n = 256 - offset;
        if ((size_t)n > size - i) n = (int)(size - i);
        switch (data[i] % 6) {
        case 0:
            CHECK(gq_blob_write(b,offset,(gq_input){data+i,n}) == SQLITE_OK);
            memcpy(model+offset,data+i,(size_t)n); break;
        case 1:
            CHECK(gq_blob_read(b,offset,(gq_output){out,n}) == SQLITE_OK);
            CHECK(!memcmp(model+offset,out,(size_t)n)); break;
        case 2: CHECK(gq_blob_read(b,INT64_MAX,(gq_output){out,1}) == GQ_INPUT); break;
        case 3: {
            int64_t length = -1;
            CHECK(gq_blob_size(b,&length) == SQLITE_OK && length == 256); break;
        }
        case 4:
            stale = b; CHECK(gq_blob_close(b) == SQLITE_OK);
            CHECK(gq_blob_open(db,table,col,1,1,&b) == SQLITE_OK);
            CHECK(gq_blob_close(stale) == GQ_HANDLE); break;
        case 5: CHECK(gq_blob_write(b,256,(gq_input){NULL,0}) == SQLITE_OK); break;
        }
    }
    CHECK(gq_blob_read(b,0,(gq_output){out,256}) == SQLITE_OK && !memcmp(model,out,256));
    run_sql(db,"ROLLBACK");
    int64_t rc = gq_blob_read(b,0,(gq_output){NULL,0}); CHECK(rc > 0 && (rc & 255) == SQLITE_ABORT);
    rc = gq_blob_close(b); CHECK(rc > 0 && (rc & 255) == SQLITE_ABORT);
    CHECK(gq_blob_close(b) == GQ_HANDLE && gq_close(db) == SQLITE_OK);
}
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size > 4096) return 0;
    uint64_t db = 0, s = 0;
    CHECK(gq_open((gq_input){(const uint8_t *)":memory:", 8}, 0, 0, 1000, &db) == SQLITE_OK);
    gq_input input = {data, (int64_t)size};
    int64_t rc = gq_prepare(db, input, &s);
    if (rc == SQLITE_OK) {
        rc = gq_step(s);
        /* Limit returned rows too; per-step work limits do not cap a stream. */
        for (int i = 0; rc == SQLITE_ROW && i < 4; ++i) rc = gq_step(s);
        (void)gq_finalize(s);
        CHECK(gq_step(s) == GQ_HANDLE);
    }
    const char *query = "SELECT ?1, ?2, ?3";
    CHECK(gq_prepare(db, (gq_input){(const uint8_t *)query, (int64_t)strlen(query)}, &s) == SQLITE_OK);
    CHECK(gq_bind(s, 1, SQLITE_BLOB, 0, 0, input) == SQLITE_OK);
    CHECK(gq_bind(s, 2, SQLITE_TEXT, 0, 0, input) == SQLITE_OK);
    CHECK(gq_bind(s, 3, SQLITE_INTEGER, (int64_t)size, 0, (gq_input){NULL, 0}) == SQLITE_OK);
    CHECK(gq_step(s) == SQLITE_ROW);
    uint8_t out[4096];
    int64_t length = -1;
    CHECK(gq_size(s, 0, SQLITE_BLOB, &length) == SQLITE_OK && length == (int64_t)size);
    CHECK(gq_fetch(s, 0, SQLITE_BLOB, (gq_output){out, length}, &length) == SQLITE_OK && length == (int64_t)size);
    CHECK(!size || !memcmp(data, out, size));
    CHECK(gq_copy(s, 1, SQLITE_TEXT, (gq_output){out, length}) == SQLITE_OK);
    CHECK(!size || !memcmp(data, out, size));
    if (size) CHECK(gq_copy(s, 0, SQLITE_BLOB, (gq_output){out, length - 1}) == GQ_LIMIT);
    CHECK(gq_type(s, 4) == GQ_INPUT);
    CHECK(gq_finalize(s) == SQLITE_OK);
    lifecycle(db, data, size);
    blob_lifecycle(data, size);
    CHECK(gq_close(db) == SQLITE_OK);
    return 0;
}
