/* SPDX-License-Identifier: Apache-2.0 */
/* Diagnostic only: raw engine cold-start reports are not a production safety proof. */
#define _POSIX_C_SOURCE 200809L
#include <pthread.h>
#include <sqlite3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WORKERS 8

typedef struct {
    int open_connection;
    int code;
    int close_code;
} Work;

static pthread_barrier_t ready;

static void require_pthread(int code, const char *operation) {
    if (code != 0) {
        fprintf(stderr, "%s failed: %d\n", operation, code);
        abort();
    }
}

static void *worker(void *argument) {
    Work *work = argument;
    int code = pthread_barrier_wait(&ready);
    if (code != PTHREAD_BARRIER_SERIAL_THREAD) require_pthread(code, "barrier wait");

    work->close_code = SQLITE_OK;
    if (work->open_connection) {
        sqlite3 *connection = NULL;
        work->code = sqlite3_open_v2(":memory:", &connection,
            SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_NOMUTEX |
            SQLITE_OPEN_PRIVATECACHE, NULL);
        /* Open failures can still return an allocated connection. */
        if (connection != NULL) work->close_code = sqlite3_close(connection);
    } else {
        work->code = sqlite3_initialize();
    }
    return NULL;
}

int main(int argc, char **argv) {
    int open_connection = 0;
    int serial = 0;
    if (argc == 2 && strcmp(argv[1], "initialize-cold") == 0) {
        /* No engine call before the worker barrier. */
    } else if (argc == 2 && strcmp(argv[1], "initialize-serial") == 0) {
        serial = 1;
    } else if (argc == 2 && strcmp(argv[1], "open-cold") == 0) {
        open_connection = 1;
    } else if (argc == 2 && strcmp(argv[1], "open-serial") == 0) {
        open_connection = 1;
        serial = 1;
    } else {
        fprintf(stderr, "usage: cold-start initialize-cold|initialize-serial|open-cold|open-serial\n");
        return 2;
    }

    if (serial) {
        int code = sqlite3_initialize();
        if (code != SQLITE_OK) {
            fprintf(stderr, "serial initialization failed: %d\n", code);
            return 1;
        }
    }

    pthread_t threads[WORKERS];
    Work work[WORKERS];
    require_pthread(pthread_barrier_init(&ready, NULL, WORKERS), "barrier initialization");
    for (int i = 0; i < WORKERS; ++i) {
        work[i] = (Work){open_connection, SQLITE_MISUSE, SQLITE_MISUSE};
        require_pthread(pthread_create(&threads[i], NULL, worker, &work[i]), "thread creation");
    }
    for (int i = 0; i < WORKERS; ++i) require_pthread(pthread_join(threads[i], NULL), "thread join");
    require_pthread(pthread_barrier_destroy(&ready), "barrier destruction");

    int succeeded = 1;
    int resources_closed = 1;
    for (int i = 0; i < WORKERS; ++i) {
        if (work[i].code != SQLITE_OK || work[i].close_code != SQLITE_OK) {
            fprintf(stderr, "worker %d failed: operation=%d close=%d\n",
                    i, work[i].code, work[i].close_code);
            succeeded = 0;
        }
        if (work[i].close_code != SQLITE_OK) resources_closed = 0;
    }
    /* A failed close leaves an engine-owned resource; never shut it down then. */
    if (!resources_closed) return 1;
    int shutdown_code = sqlite3_shutdown();
    if (shutdown_code != SQLITE_OK) {
        fprintf(stderr, "shutdown failed: %d\n", shutdown_code);
        return 1;
    }
    if (!succeeded) return 1;

    /* Identity queries/output follow all concurrent work and successful cleanup. */
    if (printf("{\"mode\":\"%s\",\"workers\":%d,\"successes\":%d,"
               "\"version\":\"%s\",\"source_id\":\"%s\"}\n",
               argv[1], WORKERS, WORKERS, sqlite3_libversion(), sqlite3_sourceid()) < 0 ||
        fflush(stdout) != 0) return 1;
    return 0;
}
