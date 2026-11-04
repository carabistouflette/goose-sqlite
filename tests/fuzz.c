/* SPDX-License-Identifier: Apache-2.0 */
#include "../native/sqlite.h"
#include <sqlite3.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do { if (!(x)) abort(); } while (0)
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
    CHECK(gq_copy(s, 0, SQLITE_BLOB, (gq_output){out, length}) == SQLITE_OK);
    CHECK(!size || !memcmp(data, out, size));
    CHECK(gq_copy(s, 1, SQLITE_TEXT, (gq_output){out, length}) == SQLITE_OK);
    CHECK(!size || !memcmp(data, out, size));
    if (size) CHECK(gq_copy(s, 0, SQLITE_BLOB, (gq_output){out, length - 1}) == GQ_LIMIT);
    CHECK(gq_type(s, 4) == GQ_INPUT);
    CHECK(gq_finalize(s) == SQLITE_OK);
    CHECK(gq_close(db) == SQLITE_OK);
    return 0;
}
