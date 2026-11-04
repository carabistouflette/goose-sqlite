/* SPDX-License-Identifier: Apache-2.0 */
#define _POSIX_C_SOURCE 200809L
#include <sqlite3.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#define CHECK(x) do { if (!(x)) abort(); } while (0)
#define SIZE 524288
static int64_t now(void) { struct timespec t; CHECK(!clock_gettime(CLOCK_MONOTONIC,&t)); return (int64_t)t.tv_sec*1000000000+t.tv_nsec; }
static sqlite3_stmt *prepare(sqlite3 *db, const char *sql) {
    sqlite3_stmt *s=NULL; CHECK(sqlite3_prepare_v2(db,sql,-1,&s,NULL) == SQLITE_OK); return s;
}
static void exec(sqlite3 *db, const char *sql) { CHECK(sqlite3_exec(db,sql,NULL,NULL,NULL) == SQLITE_OK); }
int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1],"identity")) {
        puts(sqlite3_libversion()); puts(sqlite3_sourceid());
        for (int i=0;sqlite3_compileoption_get(i);++i) puts(sqlite3_compileoption_get(i));
        return 0;
    }
    CHECK(argc == 4); int64_t n=atoll(argv[1]); int count=atoi(argv[3]);
    CHECK(n>0 && n<=10000000 && count>0 && count<=SIZE);
    int incremental=!strcmp(argv[2],"incremental"); CHECK(incremental || !strcmp(argv[2],"whole"));
    uint8_t *input=malloc(SIZE), *out=malloc(SIZE); CHECK(input && out);
    for (int i=0;i<SIZE;++i) input[i]=(uint8_t)(i%251);
    sqlite3 *db=NULL;
    CHECK(sqlite3_open_v2(":memory:",&db,SQLITE_OPEN_READWRITE|SQLITE_OPEN_CREATE|SQLITE_OPEN_NOMUTEX|SQLITE_OPEN_PRIVATECACHE,NULL) == SQLITE_OK);
    exec(db,"CREATE TABLE t(x)"); sqlite3_stmt *s=prepare(db,"INSERT INTO t VALUES(?1)");
    CHECK(sqlite3_bind_blob(s,1,input,SIZE,SQLITE_TRANSIENT) == SQLITE_OK);
    CHECK(sqlite3_step(s) == SQLITE_DONE && sqlite3_finalize(s) == SQLITE_OK);
    exec(db,"BEGIN");
    s=prepare(db,"SELECT x FROM t WHERE rowid=1"); CHECK(sqlite3_step(s) == SQLITE_ROW);
    CHECK(sqlite3_column_bytes(s,0) == SIZE); const void *p=sqlite3_column_blob(s,0); CHECK(p);
    memcpy(out,p,SIZE); CHECK(!memcmp(input,out,SIZE)); CHECK(sqlite3_finalize(s) == SQLITE_OK);
    sqlite3_blob *b=NULL; CHECK(sqlite3_blob_open(db,"main","t","x",1,0,&b) == SQLITE_OK);
    CHECK(sqlite3_blob_bytes(b) == SIZE && sqlite3_blob_read(b,out,SIZE,0) == SQLITE_OK);
    CHECK(!memcmp(input,out,SIZE) && sqlite3_blob_close(b) == SQLITE_OK);
    int64_t start, elapsed, checksum=0;
    if (incremental) {
        CHECK(sqlite3_blob_open(db,"main","t","x",1,0,&b) == SQLITE_OK);
        start=now();
        for (int64_t i=0;i<n;++i) {
            int offset=(int)((i*4093)%(SIZE-count+1));
            CHECK(sqlite3_blob_read(b,out,count,offset) == SQLITE_OK);
            CHECK(!memcmp(out,input+offset,(size_t)count)); checksum+=count;
        }
        elapsed=now()-start; CHECK(sqlite3_blob_close(b) == SQLITE_OK);
    } else {
        s=prepare(db,"SELECT x FROM t WHERE rowid=1"); CHECK(sqlite3_step(s) == SQLITE_ROW);
        start=now();
        for (int64_t i=0;i<n;++i) {
            int offset=(int)((i*4093)%(SIZE-count+1));
            CHECK(sqlite3_column_type(s,0) == SQLITE_BLOB && sqlite3_column_bytes(s,0) == SIZE);
            p=sqlite3_column_blob(s,0); CHECK(p); memcpy(out,p,SIZE);
            CHECK(!memcmp(out+offset,input+offset,(size_t)count)); checksum+=count;
        }
        elapsed=now()-start; CHECK(!memcmp(input,out,SIZE)); CHECK(sqlite3_finalize(s) == SQLITE_OK);
    }
    exec(db,"COMMIT"); CHECK(sqlite3_close(db) == SQLITE_OK); free(input); free(out);
    printf("%lld %lld\n",(long long)elapsed,(long long)checksum); return 0;
}
