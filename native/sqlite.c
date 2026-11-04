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
#define BLOBS 32
#define SQL_MAX 65536
#define VALUE_MAX 1048576
/* Registry slots are encoded in seven low token bits; generations never wrap. */
_Static_assert(DBS + STMTS + BLOBS <= 128, "token index width");
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
typedef struct {
    sqlite3_blob *ptr;
    uint64_t token;
    Database *db;
    int size;
} Blob;
typedef struct { Database db[DBS]; Statement stmt[STMTS]; Blob blob[BLOBS]; } Registry;
static pthread_key_t registry_key;
static _Thread_local Registry *thread_registry;
static int key_error;
static pthread_once_t registry_once = PTHREAD_ONCE_INIT;
static _Atomic uint64_t generation = 1;

static void destroy_registry(void *p) {
    Registry *r = p;
    /* The key is already clear. Cleanup callbacks may install a fresh registry. */
    thread_registry = NULL;
    for (int i = 0; i < STMTS; ++i) if (r->stmt[i].ptr) sqlite3_finalize(r->stmt[i].ptr);
    for (int i = 0; i < BLOBS; ++i) if (r->blob[i].ptr) sqlite3_blob_close(r->blob[i].ptr);
    for (int i = 0; i < DBS; ++i) if (r->db[i].ptr) sqlite3_close(r->db[i].ptr);
    free(r);
}
static void create_key(void) { key_error = pthread_key_create(&registry_key, destroy_registry); }
static Registry *registry(int create) {
    Registry *r = thread_registry;
    if (r || !create) return r;
    if (pthread_once(&registry_once, create_key) || key_error) return NULL;
    r = calloc(1, sizeof(*r));
    if (r && pthread_setspecific(registry_key, r)) { free(r); r = NULL; }
    /* Publish only after destructor ownership is registered successfully. */
    thread_registry = r;
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
static Blob *blob(uint64_t token) {
    Registry *r = registry(0);
    unsigned i = token & 127;
    return r && token && i >= DBS + STMTS && i < DBS + STMTS + BLOBS &&
        r->blob[i - DBS - STMTS].token == token ? &r->blob[i - DBS - STMTS] : NULL;
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
    return SQLITE_OK;
}
/* Fixed private PRAGMAs run only before installing the permanent authorizer. */
static int journal_mode(Database *d, int enable, int *wal) {
    sqlite3_stmt *s = NULL;
    d->remaining = d->budget;
    int rc = sqlite3_prepare_v2(d->ptr, enable ? "PRAGMA main.journal_mode=WAL" :
        "PRAGMA main.journal_mode", -1, &s, NULL);
    if (rc == SQLITE_OK) {
        rc = sqlite3_step(s);
        if (rc == SQLITE_ROW) {
            const unsigned char *mode = sqlite3_column_text(s, 0);
            if (!mode) rc = SQLITE_NOMEM;
            else {
                *wal = sqlite3_column_bytes(s, 0) == 3 && !memcmp(mode, "wal", 3);
                rc = sqlite3_step(s);
                if (rc == SQLITE_DONE) rc = SQLITE_OK;
            }
        } else if (rc == SQLITE_DONE) rc = SQLITE_ERROR;
    }
    int final = sqlite3_finalize(s);
    return rc == SQLITE_OK ? final : rc;
}
static int wal_fixed(void) {
    int n = sqlite3_libversion_number();
    return n >= 3051003 || (n >= 3050007 && n < 3051000) || (n >= 3044006 && n < 3045000);
}
static int set_wal(Database *d) {
    /* Preserve EXTRA; guarantee at least FULL, even with DEFAULT_WAL_SYNCHRONOUS=1. */
    sqlite3_stmt *s = NULL;
    d->remaining = d->budget;
    int rc = sqlite3_prepare_v2(d->ptr, "PRAGMA main.synchronous", -1, &s, NULL);
    int sync = 2;
    if (rc == SQLITE_OK) {
        rc = sqlite3_step(s);
        if (rc == SQLITE_ROW) {
            if (sqlite3_column_int(s, 0) > sync) sync = 3;
            rc = sqlite3_step(s);
            if (rc == SQLITE_DONE) rc = SQLITE_OK;
        } else if (rc == SQLITE_DONE) rc = SQLITE_ERROR;
    }
    int final = sqlite3_finalize(s);
    if (rc != SQLITE_OK) return rc;
    if (final != SQLITE_OK) return final;
    int wal = 0;
    rc = journal_mode(d, 1, &wal);
    if (rc != SQLITE_OK) return rc;
    if (!wal) return SQLITE_ERROR; /* No silent fallback for in-memory databases. */
    d->remaining = d->budget;
    return sqlite3_exec(d->ptr, sync == 3 ? "PRAGMA main.synchronous=EXTRA" :
        "PRAGMA main.synchronous=FULL", NULL, NULL, NULL);
}
/* No cached result: failed initialization must remain retryable. */
int64_t gq_initialize(void) { return sqlite3_initialize(); }
int64_t gq_open(gq_input path, int64_t readonly, int64_t busy_ms, int64_t budget, void *token) {
    return gq_open_config(path, readonly, busy_ms, budget, 0, token);
}
int64_t gq_open_config(gq_input path, int64_t readonly, int64_t busy_ms, int64_t budget, int64_t wal, void *token) {
    if (!token) return GQ_INPUT;
    uint64_t zero = 0; memcpy(token, &zero, sizeof zero);
    if (!valid_input(path, 4095) || !path.len || memchr(path.data, 0, (size_t)path.len) ||
        (path.len >= 5 && !memcmp(path.data, "file:", 5)) ||
        (readonly != 0 && readonly != 1) || busy_ms < 0 || busy_ms > 30000 ||
        budget < 1000 || budget > 100000000 || (wal != 0 && wal != 1) || (wal && readonly)) return GQ_INPUT;
    if (wal && !wal_fixed()) return SQLITE_MISUSE;
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
    if (rc == SQLITE_OK && !wal && (!wal_fixed() || strcmp(name, ":memory:"))) {
        /* Discover an existing WAL even when it was not explicitly requested.
           Checkpoint must see the initialized pager on an otherwise idle open.
           Exact private :memory: cannot use WAL and needs no discovery. */
        int existing_wal = 0;
        rc = journal_mode(d, 0, &existing_wal);
        if (rc == SQLITE_OK && existing_wal && !wal_fixed()) rc = SQLITE_MISUSE;
    }
    if (rc == SQLITE_OK && wal) rc = set_wal(d);
    if (rc == SQLITE_OK) rc = sqlite3_set_authorizer(d->ptr, authorize, NULL);
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
int64_t gq_checkpoint(uint64_t token, int64_t mode, void *log, void *checkpointed) {
    int64_t unavailable = -1;
    if (log) memcpy(log, &unavailable, sizeof unavailable);
    if (checkpointed) memcpy(checkpointed, &unavailable, sizeof unavailable);
    if (!log || !checkpointed) return GQ_INPUT;
    Database *d = database(token);
    if (!d) return GQ_HANDLE;
    if (mode != SQLITE_CHECKPOINT_PASSIVE && mode != SQLITE_CHECKPOINT_FULL &&
        mode != SQLITE_CHECKPOINT_RESTART && mode != SQLITE_CHECKPOINT_TRUNCATE) return GQ_INPUT;
    if (!wal_fixed()) return SQLITE_MISUSE;
    if (sqlite3_db_readonly(d->ptr, "main") != 0) return SQLITE_READONLY;
    if (!sqlite3_get_autocommit(d->ptr) || sqlite3_txn_state(d->ptr, "main") != SQLITE_TXN_NONE) return GQ_STATE;
    int frames = -1, copied = -1;
    d->remaining = d->budget;
    int rc = sqlite3_wal_checkpoint_v2(d->ptr, "main", (int)mode, &frames, &copied);
    /* BUSY may report valid partial progress. Never publish error garbage or
       engine-sized overflow as a useful frame count. */
    if ((rc == SQLITE_OK || (rc & 255) == SQLITE_BUSY) && frames >= 0 && copied >= 0 && copied <= frames) {
        int64_t n = frames, done = copied;
        memcpy(log, &n, sizeof n); memcpy(checkpointed, &done, sizeof done);
    }
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
            if (end - p < 2) return 1; /* SQLite comments may end at EOF. */
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
    /* A typed BLOB needs no encoding conversion to query its length. Preserve
       that length before materialization: OOM can turn a zeroblob into NULL.
       A connection-wide NOMEM may instead belong to another live statement. */
    if (kind == SQLITE_BLOB) {
        *n = sqlite3_column_bytes(s->ptr, (int)col);
        /* Even an empty zeroblob can allocate when expanded. No bytes are needed. */
        if (!*n) { *data = NULL; return SQLITE_OK; }
    }
    *data = kind == SQLITE_TEXT ? (const void *)sqlite3_column_text(s->ptr, (int)col)
                               : sqlite3_column_blob(s->ptr, (int)col);
    if (!*data) return SQLITE_NOMEM;
    if (kind == SQLITE_TEXT) *n = sqlite3_column_bytes(s->ptr, (int)col);
    return *n > VALUE_MAX ? GQ_LIMIT : SQLITE_OK;
}
int64_t gq_size(uint64_t token, int64_t col, int64_t kind, void *out) {
    if (!out) return GQ_INPUT;
    int64_t n = 0; memcpy(out, &n, sizeof n);
    const void *data = NULL; int rc = byte_column(token, col, kind, &data, &n);
    if (rc == SQLITE_OK) memcpy(out, &n, sizeof n);
    return rc;
}
int64_t gq_fetch(uint64_t token, int64_t col, int64_t kind, gq_output out, void *length) {
    if (!length) return GQ_INPUT;
    int64_t n = 0; memcpy(length, &n, sizeof n);
    if (out.len < 0 || out.len > VALUE_MAX || (out.len && !out.data)) return GQ_INPUT;
    const void *data = NULL;
    int rc = byte_column(token, col, kind, &data, &n);
    if (rc != SQLITE_OK) return rc;
    memcpy(length, &n, sizeof n);
    if (out.len < n) return GQ_LIMIT;
    if (n) memcpy(out.data, data, (size_t)n);
    return SQLITE_OK;
}
int64_t gq_copy(uint64_t token, int64_t col, int64_t kind, gq_output out) {
    int64_t n = 0;
    return gq_fetch(token, col, kind, out, &n);
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

int64_t gq_parameter_count(uint64_t token) {
    Statement *s = statement(token);
    return s ? sqlite3_bind_parameter_count(s->ptr) : GQ_HANDLE;
}
int64_t gq_parameter_index(uint64_t token, gq_input name) {
    Statement *s = statement(token);
    if (!s) return GQ_HANDLE;
    if (!valid_input(name, 1024) || !name.len || memchr(name.data, 0, (size_t)name.len) ||
        (name.data[0] != ':' && name.data[0] != '@' && name.data[0] != '$' && name.data[0] != '?')) return GQ_INPUT;
    char key[1025]; memcpy(key, name.data, (size_t)name.len); key[name.len] = 0;
    return sqlite3_bind_parameter_index(s->ptr, key);
}
int64_t gq_name(uint64_t token, int64_t col, gq_output out, void *length) {
    if (!length) return GQ_INPUT;
    int64_t n = 0; memcpy(length, &n, sizeof n);
    Statement *s = statement(token);
    if (!s) return GQ_HANDLE;
    if (col < 0 || col >= sqlite3_column_count(s->ptr) || out.len < 0 ||
        out.len > SQL_MAX || (out.len && !out.data)) return GQ_INPUT;
    const char *name = sqlite3_column_name(s->ptr, (int)col);
    if (!name) return SQLITE_NOMEM;
    while (n < SQL_MAX && name[n]) ++n;
    if (n == SQL_MAX && name[n]) return GQ_LIMIT;
    memcpy(length, &n, sizeof n);
    if (n > out.len) return GQ_LIMIT;
    if (n) memcpy(out.data, name, (size_t)n);
    return SQLITE_OK;
}
int64_t gq_status(uint64_t token, int64_t kind, void *out) {
    if (!out) return GQ_INPUT;
    int64_t value = 0; memcpy(out, &value, sizeof value);
    Database *d = database(token);
    if (!d) return GQ_HANDLE;
    if (kind == 0) value = sqlite3_changes64(d->ptr);
    else if (kind == 1) value = sqlite3_last_insert_rowid(d->ptr);
    else if (kind == 2) value = sqlite3_get_autocommit(d->ptr);
    else return GQ_INPUT;
    memcpy(out, &value, sizeof value);
    return SQLITE_OK;
}

int64_t gq_blob_open(uint64_t token, gq_input table, gq_input column, int64_t rowid, int64_t writable, void *out) {
    if (!out) return GQ_INPUT;
    uint64_t zero = 0; memcpy(out, &zero, sizeof zero);
    Database *d = database(token);
    if (!d) return GQ_HANDLE;
    if (!valid_input(table, 1024) || !table.len || memchr(table.data, 0, (size_t)table.len) ||
        !valid_input(column, 1024) || !column.len || memchr(column.data, 0, (size_t)column.len) ||
        (writable != 0 && writable != 1)) return GQ_INPUT;
    /* Avoid an implicit commit (and possible commit failure) on blob_close. */
    if (writable && sqlite3_get_autocommit(d->ptr)) return GQ_STATE;
    Registry *r = registry(0);
    int i = 0; while (i < BLOBS && r->blob[i].ptr) ++i;
    if (i == BLOBS) return GQ_LIMIT;
    Blob *b = &r->blob[i];
    char t[1025], c[1025];
    memcpy(t, table.data, (size_t)table.len); t[table.len] = 0;
    memcpy(c, column.data, (size_t)column.len); c[column.len] = 0;
    d->remaining = d->budget;
    int rc = sqlite3_blob_open(d->ptr, "main", t, c, rowid, (int)writable, &b->ptr);
    if (rc == SQLITE_OK) {
        b->size = sqlite3_blob_bytes(b->ptr);
        if (b->size > VALUE_MAX) rc = GQ_LIMIT;
    }
    if (rc == SQLITE_OK) {
        b->token = new_token(DBS + STMTS + i);
        if (!b->token) rc = GQ_LIMIT;
    }
    if (rc != SQLITE_OK) {
        if (b->ptr) sqlite3_blob_close(b->ptr);
        memset(b, 0, sizeof(*b));
        return rc;
    }
    b->db = d;
    memcpy(out, &b->token, sizeof b->token);
    return SQLITE_OK;
}
int64_t gq_blob_close(uint64_t token) {
    Blob *b = blob(token);
    if (!b) return GQ_HANDLE;
    int rc = sqlite3_blob_close(b->ptr);
    memset(b, 0, sizeof(*b));
    return rc;
}
int64_t gq_blob_size(uint64_t token, void *out) {
    if (!out) return GQ_INPUT;
    int64_t size = 0; memcpy(out, &size, sizeof size);
    Blob *b = blob(token);
    if (!b) return GQ_HANDLE;
    /* bytes() alone returns zero for an expired blob; probe to report ABORT. */
    uint8_t sentinel;
    b->db->remaining = b->db->budget;
    int rc = sqlite3_blob_read(b->ptr, &sentinel, 0, 0);
    if (rc == SQLITE_OK) { size = b->size; memcpy(out, &size, sizeof size); }
    return rc;
}
static int blob_range(Blob *b, int64_t offset, int64_t count) {
    return offset >= 0 && offset <= b->size && count >= 0 && count <= b->size - offset;
}
int64_t gq_blob_read(uint64_t token, int64_t offset, gq_output out) {
    Blob *b = blob(token);
    if (!b) return GQ_HANDLE;
    if (!blob_range(b, offset, out.len) || (out.len && !out.data)) return GQ_INPUT;
    uint8_t sentinel;
    b->db->remaining = b->db->budget;
    return sqlite3_blob_read(b->ptr, out.len ? out.data : &sentinel, (int)out.len, (int)offset);
}
int64_t gq_blob_write(uint64_t token, int64_t offset, gq_input in) {
    Blob *b = blob(token);
    if (!b) return GQ_HANDLE;
    if (!blob_range(b, offset, in.len) || (in.len && !in.data)) return GQ_INPUT;
    b->db->remaining = b->db->budget;
    return sqlite3_blob_write(b->ptr, in.len ? (const void *)in.data : (const void *)"", (int)in.len, (int)offset);
}
int64_t gq_backup(uint64_t source, uint64_t destination, int64_t max_pages) {
    Database *src = database(source), *dst = database(destination);
    if (!src || !dst) return GQ_HANDLE;
    if (src == dst || max_pages < 1 || max_pages > 1048576) return GQ_INPUT;
    if (!sqlite3_get_autocommit(dst->ptr) || sqlite3_txn_state(src->ptr, "main") == SQLITE_TXN_WRITE)
        return GQ_STATE;
    if (sqlite3_db_readonly(dst->ptr, "main") != 0) return SQLITE_READONLY;
    Registry *r = registry(0);
    for (int i = 0; i < STMTS; ++i) if (r->stmt[i].ptr && r->stmt[i].db == dst) return GQ_STATE;
    for (int i = 0; i < BLOBS; ++i) if (r->blob[i].ptr && r->blob[i].db == dst) return GQ_STATE;
    src->remaining = src->budget; dst->remaining = dst->budget;
    sqlite3_backup *b = sqlite3_backup_init(dst->ptr, "main", src->ptr, "main");
    if (!b) {
        int rc = sqlite3_extended_errcode(dst->ptr);
        return rc == SQLITE_OK ? SQLITE_ERROR : rc;
    }
    /* Do not access the destination connection until finish, even for errors.
       Charge requested pages: source changes can restart SQLite's progress. */
    int rc = SQLITE_OK;
    while (max_pages > 0 && rc == SQLITE_OK) {
        int pages = max_pages > 64 ? 64 : (int)max_pages;
        max_pages -= pages;
        rc = sqlite3_backup_step(b, pages);
    }
    int final = sqlite3_backup_finish(b);
    return rc == SQLITE_DONE ? final : rc == SQLITE_OK ? GQ_LIMIT : rc;
}

int64_t gq_stmt_status(uint64_t token, int64_t metric, int64_t reset, void *out) {
    if (!out) return GQ_INPUT;
    int64_t value = 0; memcpy(out, &value, sizeof value);
    Statement *s = statement(token);
    if (!s) return GQ_HANDLE;
    if ((metric < SQLITE_STMTSTATUS_FULLSCAN_STEP || metric > SQLITE_STMTSTATUS_RUN) &&
        metric != SQLITE_STMTSTATUS_MEMUSED) return GQ_INPUT;
    if (reset != 0 && reset != 1) return GQ_INPUT;
    value = sqlite3_stmt_status(s->ptr, (int)metric, (int)reset);
    memcpy(out, &value, sizeof value);
    return SQLITE_OK;
}
