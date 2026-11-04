/* SPDX-License-Identifier: Apache-2.0 */
#include "../native/sqlite.h"
#include <assert.h>
#include <sqlite3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* C caller of the SAME production adapter, not raw/unrestricted SQLite. */
static gq_input text(const char *s) { return (gq_input){(const uint8_t *)s, (int64_t)strlen(s)}; }
static uint64_t prepare(uint64_t db, const char *sql) {
    uint64_t s = 0; assert(gq_prepare(db, text(sql), &s) == SQLITE_OK); return s;
}
static void exec(uint64_t db, const char *sql) {
    uint64_t s = prepare(db, sql); assert(gq_columns(s) == 0); assert(gq_step(s) == SQLITE_DONE); assert(gq_finalize(s) == SQLITE_OK);
}
int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--identity")) {
        printf("%s\n%s\n", sqlite3_libversion(), sqlite3_sourceid());
        for (int i = 0; sqlite3_compileoption_get(i); ++i) puts(sqlite3_compileoption_get(i));
        return 0;
    }
    assert(argc == 4);
    long count = strtol(argv[1], NULL, 10), size = strtol(argv[3], NULL, 10);
    assert(count > 0 && count <= 10000000 && size >= 0 && size <= 1048576);
    uint64_t db = 0; assert(gq_open(text(":memory:"), 0, 1000, 1000000, &db) == SQLITE_OK);
    int64_t checksum = 0;
    if (!strcmp(argv[2], "prepare")) {
        for (long i = 0; i < count; ++i) {
            uint64_t s = prepare(db, "SELECT 1"); assert(gq_step(s) == SQLITE_ROW);
            int64_t value = 0; assert(gq_integer(s, 0, &value) == SQLITE_OK); checksum += value;
            assert(gq_step(s) == SQLITE_DONE); assert(gq_finalize(s) == SQLITE_OK);
        }
    } else if (!strcmp(argv[2], "text") || !strcmp(argv[2], "blob")) {
        int kind = !strcmp(argv[2], "text") ? SQLITE_TEXT : SQLITE_BLOB;
        uint8_t *input = malloc(size ? (size_t)size : 1), *out = malloc(size ? (size_t)size : 1);
        assert(input && out); memset(input, 'x', (size_t)size);
        memset(out, 0, (size_t)size); /* Match the first Goose builder resize. */
        uint64_t s = prepare(db, "SELECT ?1");
        for (long i = 0; i < count; ++i) {
            assert(gq_bind(s, 1, kind, 0, 0, (gq_input){input, size}) == SQLITE_OK);
            assert(gq_step(s) == SQLITE_ROW);
            int64_t n = -1; assert(gq_size(s, 0, kind, &n) == SQLITE_OK && n == size);
            assert(gq_copy(s, 0, kind, (gq_output){out, size}) == SQLITE_OK);
            assert(!memcmp(out, input, (size_t)size)); checksum += n;
            assert(gq_step(s) == SQLITE_DONE); assert(gq_reset(s) == SQLITE_OK);
        }
        assert(gq_finalize(s) == SQLITE_OK); free(input); free(out);
    } else {
        assert(!strcmp(argv[2], "insert"));
        exec(db, "CREATE TABLE items(x INTEGER)"); exec(db, "BEGIN");
        uint64_t s = prepare(db, "INSERT INTO items VALUES(?1)");
        for (long i = 0; i < count; ++i) {
            assert(gq_bind(s, 1, SQLITE_INTEGER, i, 0, text("")) == SQLITE_OK);
            assert(gq_step(s) == SQLITE_DONE); assert(gq_reset(s) == SQLITE_OK);
        }
        assert(gq_finalize(s) == SQLITE_OK); exec(db, "COMMIT");
        s = prepare(db, "SELECT count(*), sum(x) FROM items"); assert(gq_step(s) == SQLITE_ROW);
        assert(gq_integer(s, 0, &checksum) == SQLITE_OK && checksum == count);
        int64_t sum = 0; assert(gq_integer(s, 1, &sum) == SQLITE_OK);
        assert(sum == (int64_t)count * (count - 1) / 2);
        assert(gq_finalize(s) == SQLITE_OK);
    }
    assert(gq_close(db) == SQLITE_OK); printf("%lld\n", (long long)checksum); return 0;
}
