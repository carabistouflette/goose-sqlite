/* SPDX-License-Identifier: Apache-2.0 */
#include "sqlite.h"
#include <sqlite3.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <limits.h>

#define DBS 16
#define STMTS 64
#define SQL_MAX 65536
#define VALUE_MAX 1048576
/* Registry slots are encoded in seven low token bits; generations never wrap. */
_Static_assert(DBS + STMTS <= 128, "token index width");
typedef struct {
    sqlite3 *ptr;
    uint64_t token;
    int64_t budget, remaining;
} Database;
typedef struct {
    sqlite3_stmt *ptr;
    uint64_t token;
    Database *db;
    enum { READY, ROW, FINISHED } state;
} Statement;
typedef struct { Database db[DBS]; Statement stmt[STMTS]; } Registry;
static pthread_key_t registry_key;
static int key_error;
static pthread_once_t registry_once = PTHREAD_ONCE_INIT;
static _Atomic uint64_t generation = 1;

static void destroy_registry(void *p) {
    Registry *r = p;
    for (int i = 0; i < STMTS; ++i) if (r->stmt[i].ptr) sqlite3_finalize(r->stmt[i].ptr);
    for (int i = 0; i < DBS; ++i) if (r->db[i].ptr) sqlite3_close(r->db[i].ptr);
    free(r);
}
static void create_key(void) { key_error = pthread_key_create(&registry_key, destroy_registry); }
static Registry *registry(int create) {
    if (pthread_once(&registry_once, create_key) || key_error) return NULL;
    Registry *r = pthread_getspecific(registry_key);
    if (!r && create) {
        r = calloc(1, sizeof(*r));
        if (r && pthread_setspecific(registry_key, r)) { free(r); r = NULL; }
    }
    return r;
}
static uint64_t new_token(int index) {
    uint64_t n = atomic_load_explicit(&generation, memory_order_relaxed);
    do {
        if (n >= (UINT64_MAX >> 7)) return 0;
    } while (!atomic_compare_exchange_weak_explicit(&generation, &n, n + 1,
                 memory_order_relaxed, memory_order_relaxed));
    return (n << 7) | (uint64_t)index;
}
static Database *database(uint64_t token) {
    Registry *r = registry(0);
    unsigned i = token & 127;
    return r && token && i < DBS && r->db[i].token == token ? &r->db[i] : NULL;
}
static Statement *statement(uint64_t token) {
    Registry *r = registry(0);
    unsigned i = token & 127;
    return r && token && i >= DBS && i < DBS + STMTS && r->stmt[i - DBS].token == token
        ? &r->stmt[i - DBS] : NULL;
}
static int valid_input(gq_input x, int64_t max) {
    return x.len >= 0 && x.len <= max && (!x.len || x.data);
}
static int progress(void *p) {
    Database *d = p;
    d->remaining -= 1000;
    return d->remaining <= 0;
}
static int authorize(void *p, int action, const char *a, const char *b, const char *c, const char *d) {
    (void)p; (void)a; (void)b; (void)c; (void)d;
    return action == SQLITE_ATTACH || action == SQLITE_DETACH || action == SQLITE_PRAGMA || action == SQLITE_CREATE_VTABLE || action == SQLITE_DROP_VTABLE
        ? SQLITE_DENY : SQLITE_OK;
}
static int configure(Database *d, int busy_ms) {
    int rc = sqlite3_extended_result_codes(d->ptr, 1);
#define CONFIG(op, value) do { if (rc == SQLITE_OK) rc = sqlite3_db_config(d->ptr, op, value, NULL); } while (0)
    CONFIG(SQLITE_DBCONFIG_DEFENSIVE, 1);
    CONFIG(SQLITE_DBCONFIG_TRUSTED_SCHEMA, 0);
    CONFIG(SQLITE_DBCONFIG_ENABLE_FKEY, 1);
    CONFIG(SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION, 0);
    CONFIG(SQLITE_DBCONFIG_DQS_DML, 0);
    CONFIG(SQLITE_DBCONFIG_DQS_DDL, 0);
#undef CONFIG
    if (rc != SQLITE_OK) return rc;
    if ((rc = sqlite3_busy_timeout(d->ptr, busy_ms)) != SQLITE_OK) return rc;
    sqlite3_limit(d->ptr, SQLITE_LIMIT_LENGTH, VALUE_MAX);
    sqlite3_limit(d->ptr, SQLITE_LIMIT_SQL_LENGTH, SQL_MAX);
    sqlite3_limit(d->ptr, SQLITE_LIMIT_COLUMN, 128);
    sqlite3_limit(d->ptr, SQLITE_LIMIT_VARIABLE_NUMBER, 128);
    sqlite3_limit(d->ptr, SQLITE_LIMIT_EXPR_DEPTH, 64);
    sqlite3_limit(d->ptr, SQLITE_LIMIT_COMPOUND_SELECT, 32);
    sqlite3_limit(d->ptr, SQLITE_LIMIT_VDBE_OP, 250000);
    sqlite3_limit(d->ptr, SQLITE_LIMIT_TRIGGER_DEPTH, 16);
    sqlite3_limit(d->ptr, SQLITE_LIMIT_ATTACHED, 0);
    sqlite3_limit(d->ptr, SQLITE_LIMIT_WORKER_THREADS, 0);
    sqlite3_progress_handler(d->ptr, 1000, progress, d);
    return sqlite3_set_authorizer(d->ptr, authorize, NULL);
}
int64_t gq_open(gq_input path, int64_t readonly, int64_t busy_ms, int64_t budget, void *token) {
    if (!token) return GQ_INPUT;
    uint64_t zero = 0; memcpy(token, &zero, sizeof zero);
    if (!valid_input(path, 4095) || !path.len || memchr(path.data, 0, (size_t)path.len) ||
        (path.len >= 5 && !memcmp(path.data, "file:", 5)) ||
        (readonly != 0 && readonly != 1) || busy_ms < 0 || busy_ms > 30000 ||
        budget < 1000 || budget > 100000000) return GQ_INPUT;
    if (sqlite3_threadsafe() == 0 || sqlite3_libversion_number() < 3037000) return SQLITE_MISUSE;
    Registry *r = registry(1);
    if (!r) return SQLITE_NOMEM;
    int i = 0;
    while (i < DBS && r->db[i].ptr) ++i;
    if (i == DBS) return GQ_LIMIT;
    Database *d = &r->db[i];
    char name[4096]; memcpy(name, path.data, (size_t)path.len); name[path.len] = 0;
    int flags = (readonly ? SQLITE_OPEN_READONLY : SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE)
        | SQLITE_OPEN_NOMUTEX | SQLITE_OPEN_PRIVATECACHE;
    int rc = sqlite3_open_v2(name, &d->ptr, flags, NULL);
    d->budget = budget;
    if (rc == SQLITE_OK) rc = configure(d, (int)busy_ms);
    if (rc == SQLITE_OK) {
        d->token = new_token(i);
        if (!d->token) rc = GQ_LIMIT;
    }
    if (rc != SQLITE_OK) {
        if (d->ptr) sqlite3_close(d->ptr);
        memset(d, 0, sizeof(*d));
        return rc;
    }
    memcpy(token, &d->token, sizeof d->token);
    return SQLITE_OK;
}
int64_t gq_close(uint64_t token) {
    Database *d = database(token);
    if (!d) return GQ_HANDLE;
    int rc = sqlite3_close(d->ptr);
    if (rc == SQLITE_OK) memset(d, 0, sizeof(*d));
    return rc;
}
/* Accept only whitespace/comments after the one compiled statement. No second
   sqlite3_prepare here: preparing a rejected suffix could itself have effects. */
static int empty_tail(const char *p, const char *end) {
    while (p < end) {
        if (*p == ' ' || (*p >= '\t' && *p <= '\r')) { ++p; continue; }
        if (end - p >= 2 && p[0] == '-' && p[1] == '-') {
            p += 2; while (p < end && *p != '\n') ++p; continue;
        }
        if (end - p >= 2 && p[0] == '/' && p[1] == '*') {
            p += 2;
            while (end - p >= 2 && !(p[0] == '*' && p[1] == '/')) ++p;
            if (end - p < 2) return 0;
            p += 2; continue;
        }
        return 0;
    }
    return 1;
}
int64_t gq_prepare(uint64_t token, gq_input sql, void *out) {
    if (!out) return GQ_INPUT;
    uint64_t zero = 0; memcpy(out, &zero, sizeof zero);
    Database *d = database(token);
    if (!d) return GQ_HANDLE;
    if (!valid_input(sql, SQL_MAX) || !sql.len || memchr(sql.data, 0, (size_t)sql.len)) return GQ_INPUT;
    Registry *r = registry(0);
    int i = 0; while (i < STMTS && r->stmt[i].ptr) ++i;
    if (i == STMTS) return GQ_LIMIT;
    Statement *s = &r->stmt[i];
    const char *tail = NULL;
    d->remaining = d->budget;
    int rc = sqlite3_prepare_v3(d->ptr, (const char *)sql.data, (int)sql.len,
                               SQLITE_PREPARE_PERSISTENT, &s->ptr, &tail);
    if (rc == SQLITE_OK && (!s->ptr || !empty_tail(tail, (const char *)sql.data + sql.len))) rc = GQ_INPUT;
    if (rc == SQLITE_OK) {
        s->token = new_token(DBS + i);
        if (!s->token) rc = GQ_LIMIT;
    }
    if (rc != SQLITE_OK) {
        if (s->ptr) sqlite3_finalize(s->ptr);
        memset(s, 0, sizeof(*s)); return rc;
    }
    s->db = d; s->state = READY;
    memcpy(out, &s->token, sizeof s->token);
    return SQLITE_OK;
}
int64_t gq_finalize(uint64_t token) {
    Statement *s = statement(token);
    if (!s) return GQ_HANDLE;
    int rc = sqlite3_finalize(s->ptr);
    memset(s, 0, sizeof(*s));
    return rc;
}
int64_t gq_reset(uint64_t token) {
    Statement *s = statement(token);
    if (!s) return GQ_HANDLE;
    int rc = sqlite3_reset(s->ptr);
    s->state = READY;
    return rc;
}
int64_t gq_clear(uint64_t token) {
    Statement *s = statement(token);
    if (!s) return GQ_HANDLE;
    if (s->state != READY) return GQ_STATE;
    return sqlite3_clear_bindings(s->ptr);
}
int64_t gq_bind(uint64_t token, int64_t index, int64_t kind, int64_t integer, double real, gq_input bytes) {
    Statement *s = statement(token);
    if (!s) return GQ_HANDLE;
    if (s->state != READY) return GQ_STATE;
    if (index < 1 || index > sqlite3_bind_parameter_count(s->ptr)) return GQ_INPUT;
    switch (kind) {
    case SQLITE_NULL: return sqlite3_bind_null(s->ptr, (int)index);
    case SQLITE_INTEGER: return sqlite3_bind_int64(s->ptr, (int)index, integer);
    case SQLITE_FLOAT:
        if (!isfinite(real)) return GQ_INPUT;
        return sqlite3_bind_double(s->ptr, (int)index, real);
    case SQLITE_TEXT: case SQLITE_BLOB:
        if (!valid_input(bytes, VALUE_MAX)) return GQ_INPUT;
        /* Non-null sentinel prevents SQLite treating empty bytes as SQL NULL. */
        if (kind == SQLITE_TEXT) return sqlite3_bind_text(s->ptr, (int)index,
            bytes.len ? (const char *)bytes.data : "", (int)bytes.len, SQLITE_TRANSIENT);
        return sqlite3_bind_blob(s->ptr, (int)index,
            bytes.len ? (const void *)bytes.data : (const void *)"", (int)bytes.len, SQLITE_TRANSIENT);
    default: return GQ_INPUT;
    }
}
int64_t gq_step(uint64_t token) {
    Statement *s = statement(token);
    if (!s) return GQ_HANDLE;
    if (s->state == FINISHED) return GQ_STATE;
    s->db->remaining = s->db->budget;
    int rc = sqlite3_step(s->ptr);
    s->state = rc == SQLITE_ROW ? ROW : FINISHED;
    return rc;
}
int64_t gq_columns(uint64_t token) {
    Statement *s = statement(token);
    return s ? sqlite3_column_count(s->ptr) : GQ_HANDLE;
}
static int column(uint64_t token, int64_t col, Statement **out) {
    Statement *s = statement(token);
    if (!s) return GQ_HANDLE;
    if (s->state != ROW) return GQ_STATE;
    if (col < 0 || col >= sqlite3_column_count(s->ptr)) return GQ_INPUT;
    *out = s; return SQLITE_OK;
}
int64_t gq_type(uint64_t token, int64_t col) {
    Statement *s = NULL; int rc = column(token, col, &s);
    return rc == SQLITE_OK ? sqlite3_column_type(s->ptr, (int)col) : rc;
}
int64_t gq_integer(uint64_t token, int64_t col, void *out) {
    if (!out) return GQ_INPUT;
    int64_t value = 0; memcpy(out, &value, sizeof value);
    Statement *s = NULL; int rc = column(token, col, &s);
    if (rc != SQLITE_OK) return rc;
    if (sqlite3_column_type(s->ptr, (int)col) != SQLITE_INTEGER) return GQ_TYPE;
    value = sqlite3_column_int64(s->ptr, (int)col); memcpy(out, &value, sizeof value);
    return SQLITE_OK;
}
int64_t gq_real(uint64_t token, int64_t col, void *out) {
    if (!out) return GQ_INPUT;
    double value = 0; memcpy(out, &value, sizeof value);
    Statement *s = NULL; int rc = column(token, col, &s);
    if (rc != SQLITE_OK) return rc;
    if (sqlite3_column_type(s->ptr, (int)col) != SQLITE_FLOAT) return GQ_TYPE;
    value = sqlite3_column_double(s->ptr, (int)col); memcpy(out, &value, sizeof value);
    return SQLITE_OK;
}
static int byte_column(uint64_t token, int64_t col, int64_t kind, const void **data, int64_t *n) {
    Statement *s = NULL; int rc = column(token, col, &s);
    if (rc != SQLITE_OK) return rc;
    if (kind != SQLITE_TEXT && kind != SQLITE_BLOB) return GQ_INPUT;
    if (sqlite3_column_type(s->ptr, (int)col) != kind) return GQ_TYPE;
    *data = kind == SQLITE_TEXT ? (const void *)sqlite3_column_text(s->ptr, (int)col)
                               : sqlite3_column_blob(s->ptr, (int)col);
    *n = sqlite3_column_bytes(s->ptr, (int)col);
    if (!*data && (kind == SQLITE_TEXT || *n)) return SQLITE_NOMEM;
    return *n > VALUE_MAX ? GQ_LIMIT : SQLITE_OK;
}
int64_t gq_size(uint64_t token, int64_t col, int64_t kind, void *out) {
    if (!out) return GQ_INPUT;
    int64_t n = 0; memcpy(out, &n, sizeof n);
    const void *data = NULL; int rc = byte_column(token, col, kind, &data, &n);
    if (rc == SQLITE_OK) memcpy(out, &n, sizeof n);
    return rc;
}
int64_t gq_copy(uint64_t token, int64_t col, int64_t kind, gq_output out) {
    if (out.len < 0 || out.len > VALUE_MAX || (out.len && !out.data)) return GQ_INPUT;
    const void *data = NULL; int64_t n = 0;
    int rc = byte_column(token, col, kind, &data, &n);
    if (rc != SQLITE_OK) return rc;
    if (out.len < n) return GQ_LIMIT;
    if (n) memcpy(out.data, data, (size_t)n);
    return SQLITE_OK;
}
int64_t gq_message(uint64_t token, gq_output out) {
    Database *d = database(token);
    if (!d) return GQ_HANDLE;
    if (out.len < 0 || out.len > 4096 || (out.len && !out.data)) return GQ_INPUT;
    const char *text = sqlite3_errmsg(d->ptr);
    size_t n = strlen(text);
    if (n > (size_t)out.len) return GQ_LIMIT;
    if (n) memcpy(out.data, text, n);
    return (int64_t)n;
}
