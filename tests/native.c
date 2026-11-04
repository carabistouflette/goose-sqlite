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
#include <math.h>

static gq_input text(const char *s) { return (gq_input){(const uint8_t *)s, (int64_t)strlen(s)}; }
static uint64_t open_db(const char *path, int readonly, int busy) {
    uint64_t d = 0; assert(gq_open(text(path), readonly, busy, 1000000, &d) == SQLITE_OK); return d;
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
static void *foreign(void *p) {
    uint64_t *tokens = p;
    assert(gq_close(tokens[0]) == GQ_HANDLE);
    assert(gq_step(tokens[1]) == GQ_HANDLE);
    assert(gq_parameter_count(tokens[1]) == GQ_HANDLE);
    assert(gq_parameter_index(tokens[1], text(":x")) == GQ_HANDLE);
    int64_t value = 17;
    assert(gq_stmt_status(tokens[1],SQLITE_STMTSTATUS_RUN,0,&value) == GQ_HANDLE && value == 0);
    assert(gq_status(tokens[0], 0, &value) == GQ_HANDLE && value == 0);
    uint8_t bytes[8];
    assert(gq_name(tokens[1], 0, (gq_output){bytes, 8}, &value) == GQ_HANDLE && value == 0);
    uint64_t d = open_db(":memory:", 0, 0);
    uint64_t s = prepare(d, "SELECT 7");
    assert(gq_step(s) == SQLITE_ROW);
    assert(gq_step(tokens[1]) == GQ_HANDLE);
    assert(gq_finalize(s) == SQLITE_OK); assert(gq_close(d) == SQLITE_OK);
    return NULL;
}
static void *abandon(void *p) {
    uint64_t d = open_db(p, 0, 0);
    assert(exec(d, "BEGIN EXCLUSIVE") == SQLITE_OK);
    (void)prepare(d, "SELECT 1");
    return NULL; /* Registry destructor must roll back and release locks. */
}
static void *abandon_returning(void *p) {
    uint64_t d = open_db(p, 0, 0);
    uint64_t implicit = prepare(d, "INSERT INTO t VALUES(3) RETURNING x");
    assert(gq_step(implicit) == SQLITE_ROW);
    return NULL; /* Finalization can commit this implicit write. */
}
static void *abandon_explicit_returning(void *p) {
    uint64_t d = open_db(p, 0, 0);
    assert(exec(d, "BEGIN") == SQLITE_OK);
    uint64_t explicit_write = prepare(d, "INSERT INTO t VALUES(4) RETURNING x");
    assert(gq_step(explicit_write) == SQLITE_ROW);
    return NULL; /* Close must roll back the still-open explicit transaction. */
}
/* A trusted native cleanup callback can re-enter during thread destruction. */
typedef struct { uint64_t token; } Cleanup;
static _Thread_local Cleanup *cleanup_context;
static _Thread_local int reentering;
static int cleanup_calls;
static void cleanup_scalar(sqlite3_context *c,int argc,sqlite3_value **argv) {
    (void)argc; (void)argv; sqlite3_result_null(c);
}
static void cleanup_reenter(void *p) {
    Cleanup *c=p;
    if (!c->token || reentering) { free(c); return; }
    reentering=1; cleanup_context=NULL;
    int64_t value=123;
    assert(gq_status(c->token,2,&value)==GQ_HANDLE && value==0);
    uint64_t fresh=open_db(":memory:",0,0), stmt=prepare(fresh,"SELECT 7");
    assert(gq_step(stmt)==SQLITE_ROW && gq_integer(stmt,0,&value)==SQLITE_OK && value==7);
    assert(gq_finalize(stmt)==SQLITE_OK && gq_close(fresh)==SQLITE_OK);
    ++cleanup_calls; free(c); reentering=0;
}
static int cleanup_extension(sqlite3 *db,char **error,const sqlite3_api_routines *api) {
    (void)error; (void)api;
    Cleanup *c=calloc(1,sizeof(*c)); if (!c) return SQLITE_NOMEM;
    int rc=sqlite3_create_function_v2(db,"test_registry_cleanup",0,SQLITE_UTF8,c,cleanup_scalar,NULL,NULL,cleanup_reenter);
    if (rc==SQLITE_OK) cleanup_context=c;
    return rc; /* SQLite destroys userdata on registration failure too. */
}
static void *abandon_with_callback(void *unused) {
    (void)unused;
    assert(sqlite3_auto_extension((void (*)(void))cleanup_extension)==SQLITE_OK);
    uint64_t d=open_db(":memory:",0,0);
    assert(cleanup_context); cleanup_context->token=d;
    sqlite3_reset_auto_extension();
    (void)prepare(d,"SELECT 1");
    return NULL;
}
int main(void) {
    uint64_t d = open_db(":memory:", 0, 0), s = prepare(d, "SELECT ?1, ?2, ?3, ?4");
    uint8_t unaligned[17] = {0};
    assert(gq_stmt_status(s,SQLITE_STMTSTATUS_RUN,0,unaligned+1) == SQLITE_OK);
    int64_t status; memcpy(&status,unaligned+1,8); assert(status == 0);
    assert(gq_stmt_status(s,INT64_MAX,0,unaligned+1) == GQ_INPUT);
    memcpy(&status,unaligned+1,8); assert(status == 0);
    assert(gq_stmt_status(s,SQLITE_STMTSTATUS_RUN,2,unaligned+1) == GQ_INPUT);
    assert(gq_stmt_status(s,SQLITE_STMTSTATUS_RUN,0,NULL) == GQ_INPUT);
    assert(gq_parameter_count(s) == 4);
    assert(gq_parameter_index(s, text("?1")) == 1);
    assert(gq_parameter_count(d) == GQ_HANDLE);
    uint8_t guards[] = {17,18,19,20,21,22};
    assert(gq_name(s, 0, (gq_output){guards+1, 1}, unaligned+1) == GQ_LIMIT);
    int64_t name_size; memcpy(&name_size, unaligned+1, 8); assert(name_size == 2);
    assert(guards[0] == 17 && guards[1] == 18 && guards[5] == 22);
    assert(gq_name(s, 0, (gq_output){guards+1, 2}, unaligned+1) == SQLITE_OK);
    assert(guards[0] == 17 && guards[1] == '?' && guards[2] == '1' && guards[3] == 20);
    assert(gq_name(s, 9, (gq_output){guards, 6}, unaligned+1) == GQ_INPUT);
    memcpy(&name_size, unaligned+1, 8); assert(name_size == 0);
    assert(gq_status(d, 2, unaligned+1) == SQLITE_OK);
    memcpy(&name_size, unaligned+1, 8); assert(name_size == 1);
    assert(gq_status(s, 0, unaligned+1) == GQ_HANDLE);
    memcpy(&name_size, unaligned+1, 8); assert(name_size == 0);

    assert(gq_bind(s, 1, SQLITE_INTEGER, INT64_MIN, 0, text("")) == SQLITE_OK);
    assert(gq_bind(s, 2, SQLITE_FLOAT, 0, 1.25, text("")) == SQLITE_OK);
    assert(gq_bind(s, 3, SQLITE_TEXT, 0, 0, (gq_input){NULL, 0}) == SQLITE_OK);
    assert(gq_bind(s, 4, SQLITE_BLOB, 0, 0, (gq_input){NULL, 0}) == SQLITE_OK);
    assert(gq_bind(s, 2, SQLITE_FLOAT, 0, NAN, text("")) == GQ_INPUT);
    assert(gq_bind(s, 2, SQLITE_FLOAT, 0, INFINITY, text("")) == GQ_INPUT);
    assert(gq_step(s) == SQLITE_ROW);
    assert(gq_integer(s, 0, unaligned + 1) == SQLITE_OK);
    int64_t integer; memcpy(&integer, unaligned + 1, 8); assert(integer == INT64_MIN);
    assert(gq_real(s, 1, unaligned + 1) == SQLITE_OK);
    double real; memcpy(&real, unaligned + 1, 8); assert(real == 1.25);
    assert(gq_type(s, 2) == SQLITE_TEXT && gq_type(s, 3) == SQLITE_BLOB);
    assert(gq_copy(s, 2, SQLITE_TEXT, (gq_output){NULL, 0}) == SQLITE_OK);
    assert(gq_copy(s, 3, SQLITE_BLOB, (gq_output){NULL, 0}) == SQLITE_OK);
    pthread_t worker; uint64_t tokens[] = {d, s};
    assert(!pthread_create(&worker, NULL, foreign, tokens)); assert(!pthread_join(worker, NULL));
    assert(gq_step(s) == SQLITE_DONE && gq_step(s) == GQ_STATE);
    assert(gq_reset(s) == SQLITE_OK);
    int64_t invalid_length = 7;
    assert(gq_fetch(s, 0, SQLITE_INTEGER, (gq_output){NULL,0}, &invalid_length) == GQ_STATE && invalid_length == 0);
    assert(gq_fetch(s, 0, SQLITE_TEXT, (gq_output){NULL,1}, &invalid_length) == GQ_INPUT && invalid_length == 0);
    assert(gq_fetch(s, 0, SQLITE_TEXT, (gq_output){NULL,0}, NULL) == GQ_INPUT);
    uint8_t bytes[] = {'a', 0, 255};
    assert(gq_bind(s, 3, SQLITE_TEXT, 0, 0, (gq_input){bytes, 3}) == SQLITE_OK);
    bytes[0] = 'z';
    assert(gq_step(s) == SQLITE_ROW);
    uint8_t guarded[] = {17, 18, 19, 20, 21};
    assert(gq_fetch(s, 2, SQLITE_TEXT, (gq_output){guarded + 1, 2}, unaligned + 1) == GQ_LIMIT);
    int64_t needed; memcpy(&needed, unaligned + 1, 8); assert(needed == 3);
    assert(gq_copy(s, 2, SQLITE_TEXT, (gq_output){guarded + 1, 2}) == GQ_LIMIT);
    assert(guarded[1] == 18 && guarded[3] == 20);
    assert(gq_copy(s, 2, SQLITE_TEXT, (gq_output){guarded + 1, 3}) == SQLITE_OK);
    assert(guarded[0] == 17 && guarded[1] == 'a' && guarded[2] == 0 && guarded[3] == 255 && guarded[4] == 21);
    assert(gq_integer(s, 2, unaligned + 1) == GQ_TYPE);
    assert(gq_copy(s, 2, SQLITE_TEXT, (gq_output){NULL, 3}) == GQ_INPUT);
    assert(gq_close(d) == SQLITE_BUSY);
    assert(gq_finalize(s) == SQLITE_OK);
    uint64_t stale = s;
    for (int i = 0; i < 1000; ++i) {
        s = prepare(d, "SELECT 1"); assert(gq_step(stale) == GQ_HANDLE); assert(gq_finalize(s) == SQLITE_OK);
    }
    uint64_t statements[64];
    for (int i = 0; i < 64; ++i) statements[i] = prepare(d, "SELECT 1");
    s = 123; assert(gq_prepare(d, text("SELECT 1"), &s) == GQ_LIMIT && s == 0);
    for (int i = 0; i < 64; ++i) assert(gq_finalize(statements[i]) == SQLITE_OK);
    uint64_t dbs[15]; for (int i = 0; i < 15; ++i) dbs[i] = open_db(":memory:", 0, 0);
    s = 123; assert(gq_open(text(":memory:"), 0, 0, 1000, &s) == GQ_LIMIT && s == 0);
    for (int i = 0; i < 15; ++i) assert(gq_close(dbs[i]) == SQLITE_OK);
    assert(gq_close(d) == SQLITE_OK && gq_close(d) == GQ_HANDLE);
    assert(gq_open((gq_input){NULL, 1}, 0, 0, 1000, &s) == GQ_INPUT);
    assert(gq_open(text(":memory:"), 0, 30001, 1000, &s) == GQ_INPUT);
    assert(gq_open(text(":memory:"), 0, 0, 999, &s) == GQ_INPUT);
    assert(gq_open(text(":memory:"), 0, 0, 1000, unaligned + 1) == SQLITE_OK);
    memcpy(&d, unaligned + 1, 8); assert(gq_close(d) == SQLITE_OK);

    char path[] = "/tmp/goose-sqlite-test-XXXXXX";
    int fd = mkstemp(path); assert(fd >= 0); assert(!close(fd));
    d = open_db(path, 0, 0);
    assert(exec(d, "CREATE TABLE t(x UNIQUE)") == SQLITE_OK);
    uint64_t second = open_db(path, 0, 1);
    assert(exec(d, "BEGIN IMMEDIATE") == SQLITE_OK);
    assert(exec(second, "INSERT INTO t VALUES(1)") == SQLITE_BUSY);
    assert(exec(d, "ROLLBACK") == SQLITE_OK);
    assert(exec(second, "INSERT INTO t VALUES(1)") == SQLITE_OK);
    s = prepare(second, "INSERT INTO t VALUES(1)");
    assert(gq_step(s) == SQLITE_CONSTRAINT_UNIQUE);
    assert(gq_step(s) == GQ_STATE);
    assert(gq_reset(s) == SQLITE_CONSTRAINT_UNIQUE);
    assert(gq_finalize(s) == SQLITE_OK);
    s = prepare(second, "INSERT INTO t VALUES(1)");
    assert(gq_step(s) == SQLITE_CONSTRAINT_UNIQUE);
    assert(gq_finalize(s) == SQLITE_CONSTRAINT_UNIQUE);
    assert(gq_finalize(s) == GQ_HANDLE);
    assert(gq_close(second) == SQLITE_OK && gq_close(d) == SQLITE_OK);
    d = open_db(path, 1, 0);
    assert((exec(d, "INSERT INTO t VALUES(2)") & 255) == SQLITE_READONLY);
    assert(gq_close(d) == SQLITE_OK);
    assert(!pthread_create(&worker, NULL, abandon, path)); assert(!pthread_join(worker, NULL));
    d = open_db(path, 0, 0); assert(exec(d, "INSERT INTO t VALUES(2)") == SQLITE_OK);
    assert(gq_close(d) == SQLITE_OK);
    assert(!pthread_create(&worker, NULL, abandon_returning, path)); assert(!pthread_join(worker, NULL));
    assert(!pthread_create(&worker, NULL, abandon_explicit_returning, path)); assert(!pthread_join(worker, NULL));
    d = open_db(path, 0, 0);
    s = prepare(d, "SELECT count(*), sum(x) FROM t");
    assert(gq_step(s) == SQLITE_ROW);
    int64_t rows = 0, sum = 0;
    assert(gq_integer(s, 0, &rows) == SQLITE_OK && rows == 3);
    assert(gq_integer(s, 1, &sum) == SQLITE_OK && sum == 6);
    assert(gq_finalize(s) == SQLITE_OK && gq_close(d) == SQLITE_OK);
    assert(!unlink(path));
    d=open_db(":memory:",0,0); s=prepare(d,"SELECT 11");
    assert(!pthread_create(&worker,NULL,abandon_with_callback,NULL) && !pthread_join(worker,NULL));
    assert(cleanup_calls==1 && gq_step(s)==SQLITE_ROW);
    assert(gq_integer(s,0,&rows)==SQLITE_OK && rows==11);
    assert(gq_finalize(s)==SQLITE_OK && gq_close(d)==SQLITE_OK);
    puts("sqlite native tests passed");
    return 0;
}
