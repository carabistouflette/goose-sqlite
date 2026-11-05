/* SPDX-License-Identifier: Apache-2.0 */
/* Test-only policy inspection, never linked into the public package. */
#include "../../native/sqlite.h"
#include <sqlite3.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static sqlite3 *captured[2];
static int captured_count;
static void require(int ok) { if (!ok) abort(); }
static int capture(sqlite3 *db, char **error, const sqlite3_api_routines *api) {
    (void)error; (void)api;
    require(captured_count < 2); captured[captured_count++] = db; return SQLITE_OK;
}
static gq_input text(const char *value) {
    return (gq_input){(const uint8_t *)value, (int64_t)strlen(value)};
}
int main(int argc, char **argv) {
    require(argc == 2);
    require(sqlite3_auto_extension((void (*)(void))capture) == SQLITE_OK);
    uint64_t db[2] = {0, 0};
    const char *sql[] = {"PRAGMA journal_mode", "PRAGMA synchronous", "PRAGMA page_size",
        "PRAGMA cache_size", "PRAGMA wal_autocheckpoint", "PRAGMA foreign_keys",
        "PRAGMA trusted_schema", "PRAGMA locking_mode", "PRAGMA busy_timeout"};
    char values[2][9][32];
    for (int connection = 0; connection < 2; ++connection) {
        uint64_t denied = 0;
        require(gq_open_config(text(argv[1]), 0, 0, 100000000, 0, &db[connection]) == SQLITE_OK);
        require(captured_count == connection + 1);
        require(gq_prepare(db[connection], text("PRAGMA synchronous"), &denied) == SQLITE_AUTH);
        require(!denied);
        /* Only this isolated probe removes authorizers, after checking denial.
           Fixed read-only PRAGMAs inspect two simultaneously open connections;
           these test routines are never linked into the public package. */
        require(sqlite3_set_authorizer(captured[connection], NULL, NULL) == SQLITE_OK);
        for (size_t i = 0; i < sizeof sql / sizeof sql[0]; ++i) {
            sqlite3_stmt *stmt = NULL;
            require(sqlite3_prepare_v2(captured[connection], sql[i], -1, &stmt, NULL) == SQLITE_OK);
            require(sqlite3_step(stmt) == SQLITE_ROW);
            const unsigned char *value = sqlite3_column_text(stmt, 0);
            require(value != NULL);
            size_t length = strlen((const char *)value);
            require(length < sizeof values[connection][i]);
            memcpy(values[connection][i], value, length + 1);
            if (connection) require(!strcmp(values[0][i], values[1][i]));
            require(sqlite3_step(stmt) == SQLITE_DONE);
            require(sqlite3_finalize(stmt) == SQLITE_OK);
        }
    }
    require(gq_close(db[1]) == SQLITE_OK);
    require(gq_close(db[0]) == SQLITE_OK);
    printf("policy");
    for (size_t i = 0; i < sizeof sql / sizeof sql[0]; ++i) printf(" %s", values[0][i]);
    puts("");
    sqlite3_reset_auto_extension();
    return 0;
}
