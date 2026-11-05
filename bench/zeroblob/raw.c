/* SPDX-License-Identifier: Apache-2.0 */
#define _POSIX_C_SOURCE 200809L
#include <sqlite3.h>
#include "../../native/sqlite.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define CHECK(x) do { if (!(x)) abort(); } while (0)
static int mode_for(const char *s) {
    if (!strcmp(s,"copy")) return 0;
    if (!strcmp(s,"zero")) return 1;
    CHECK(!strcmp(s,"sql")); return 2;
}
static long long number(const char *s) {
    char *end=NULL;long long n=strtoll(s,&end,10);CHECK(*s && end && !*end);return n;
}
static const char *sql_for(int mode) { return mode==2 ? "SELECT zeroblob(?1)" : "SELECT ?1"; }
static void verify(const uint8_t *out,int size) { for (int i=0;i<size;++i) CHECK(out[i]==0); }
static sqlite3 *open_db(void) {
    sqlite3 *d=NULL;
    CHECK(sqlite3_open_v2(":memory:",&d,SQLITE_OPEN_READWRITE|SQLITE_OPEN_CREATE|SQLITE_OPEN_NOMUTEX|SQLITE_OPEN_PRIVATECACHE,NULL)==SQLITE_OK);
    CHECK(sqlite3_extended_result_codes(d,1)==SQLITE_OK && sqlite3_busy_timeout(d,1000)==SQLITE_OK);
    return d;
}
static sqlite3_stmt *prepare(sqlite3 *d,int mode) {
    sqlite3_stmt *s=NULL;
    CHECK(sqlite3_prepare_v3(d,sql_for(mode),-1,SQLITE_PREPARE_PERSISTENT,&s,NULL)==SQLITE_OK);return s;
}
static void bind(sqlite3_stmt *s,int mode,int size,const uint8_t *input) {
    int rc=mode==0 ? sqlite3_bind_blob(s,1,input,size,SQLITE_TRANSIENT) :
           mode==1 ? sqlite3_bind_zeroblob64(s,1,(sqlite3_uint64)size) : sqlite3_bind_int64(s,1,size);
    CHECK(rc==SQLITE_OK);
}
static void read_row(sqlite3_stmt *s,int size,uint8_t *out) {
    CHECK(sqlite3_step(s)==SQLITE_ROW && sqlite3_column_type(s,0)==SQLITE_BLOB);
    CHECK(sqlite3_column_bytes(s,0)==size); /* Strict BLOB length needs no conversion. */
    if (size) { const void *p=sqlite3_column_blob(s,0); CHECK(p);memcpy(out,p,(size_t)size); }
    verify(out,size);
    CHECK(sqlite3_step(s)==SQLITE_DONE && sqlite3_reset(s)==SQLITE_OK);
}
static void identity(void) {
    puts(sqlite3_libversion());puts(sqlite3_sourceid());
    for (int i=0;sqlite3_compileoption_get(i);++i) puts(sqlite3_compileoption_get(i));
}
#ifdef GQ_DIAGNOSTIC
static gq_input text(const char *s) { return (gq_input){(const uint8_t *)s,(int64_t)strlen(s)}; }
static void diagnostic(int checked,int mode,int size,const uint8_t *input,uint8_t *out) {
    sqlite3_int64 before,after;
    if (checked) {
        CHECK(gq_initialize()==SQLITE_OK);uint64_t d=0,s=0;
        CHECK(gq_open(text(":memory:"),0,1000,1000000,&d)==SQLITE_OK);
        CHECK(gq_prepare(d,text(sql_for(mode)),&s)==SQLITE_OK);
        before=sqlite3_memory_used();CHECK(before>0);
        int64_t rc=mode==0 ? gq_bind(s,1,SQLITE_BLOB,0,0,(gq_input){input,size}) :
                   mode==1 ? gq_bind_zeroblob(s,1,size) : gq_bind(s,1,SQLITE_INTEGER,size,0,text(""));
        CHECK(rc==SQLITE_OK);after=sqlite3_memory_used();
        CHECK(gq_step(s)==SQLITE_ROW);int64_t length=-1;
        CHECK(gq_fetch(s,0,SQLITE_BLOB,(gq_output){out,size},&length)==SQLITE_OK && length==size);
        verify(out,size);CHECK(gq_step(s)==SQLITE_DONE);
        CHECK(gq_finalize(s)==SQLITE_OK && gq_close(d)==SQLITE_OK);
    } else {
        sqlite3 *d=open_db();sqlite3_stmt *s=prepare(d,mode);before=sqlite3_memory_used();CHECK(before>0);
        bind(s,mode,size,input);after=sqlite3_memory_used();read_row(s,size,out);
        CHECK(sqlite3_finalize(s)==SQLITE_OK && sqlite3_close(d)==SQLITE_OK);
    }
    CHECK(sqlite3_shutdown()==SQLITE_OK && sqlite3_memory_used()==0);
    printf("{\"driver\":\"%s\",\"mode\":\"%s\",\"bytes\":%d,\"sqlite_before\":%lld,\"sqlite_after_bind\":%lld,\"sqlite_delta\":%lld,\"verified_bytes\":%d}\n",
           checked ? "checked-native-abi":"raw-c-api",mode==0 ? "copy":mode==1 ? "zero":"sql",size,
           (long long)before,(long long)after,(long long)(after-before),size);
}
#else
static int64_t now(void) { struct timespec t; CHECK(!clock_gettime(CLOCK_MONOTONIC,&t));return (int64_t)t.tv_sec*1000000000+t.tv_nsec; }
#endif
int main(int argc,char **argv) {
    if (argc==2 && !strcmp(argv[1],"identity")) { identity();return 0; }
    CHECK(argc==4);int mode=mode_for(argv[2]);long long parsed=number(argv[3]);
    CHECK(parsed>=0 && parsed<=1048576);int size=(int)parsed;
    uint8_t *input=mode==0 ? calloc((size_t)(size ? size : 1),1) : NULL,*out=malloc((size_t)(size ? size : 1));
    CHECK((mode!=0 || input) && out);
#ifdef GQ_DIAGNOSTIC
    CHECK(!strcmp(argv[1],"raw") || !strcmp(argv[1],"checked"));
    /* Separate process: this diagnostic changes allocator accounting before init. */
    CHECK(sqlite3_config(SQLITE_CONFIG_MEMSTATUS,1)==SQLITE_OK);
    diagnostic(!strcmp(argv[1],"checked"),mode,size,input,out);
#else
    long long n=number(argv[1]);CHECK(n>0 && n<=10000000);
    CHECK(sqlite3_initialize()==SQLITE_OK);sqlite3 *d=open_db();sqlite3_stmt *s=prepare(d,mode);
    bind(s,mode,size,input);read_row(s,size,out); /* Prime the same statement. */
    int64_t checksum=0,start=now();
    for (long long i=0;i<n;++i) { bind(s,mode,size,input);read_row(s,size,out);checksum+=size+1; }
    int64_t elapsed=now()-start;
    CHECK(sqlite3_finalize(s)==SQLITE_OK && sqlite3_close(d)==SQLITE_OK);
    printf("%lld %lld\n",(long long)elapsed,(long long)checksum);
#endif
    free(input);free(out);return 0;
}
