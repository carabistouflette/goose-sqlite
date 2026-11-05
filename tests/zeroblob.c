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

#define MAX_VALUE 1048576
static int checked_values;
static gq_input text(const char *s) { return (gq_input){(const uint8_t *)s,(int64_t)strlen(s)}; }
static uint64_t open_db(void) {
    uint64_t d=0; assert(gq_open(text(":memory:"),0,0,1000000,&d)==SQLITE_OK); return d;
}
static uint64_t prepare(uint64_t d,const char *sql) {
    uint64_t s=0; assert(gq_prepare(d,text(sql),&s)==SQLITE_OK); return s;
}
static int64_t exec(uint64_t d,const char *sql) {
    uint64_t s=prepare(d,sql); int64_t rc=gq_step(s),final=gq_finalize(s);
    return rc==SQLITE_DONE ? final : rc;
}
static int64_t scalar(uint64_t d,const char *sql) {
    uint64_t s=prepare(d,sql); int64_t n=0;
    assert(gq_step(s)==SQLITE_ROW && gq_integer(s,0,&n)==SQLITE_OK);
    assert(gq_step(s)==SQLITE_DONE && gq_finalize(s)==SQLITE_OK); return n;
}
static void zeros(uint64_t s,int64_t size) {
    assert(gq_step(s)==SQLITE_ROW && gq_type(s,0)==SQLITE_BLOB);
    int64_t length=-1,value=123;
    assert(gq_size(s,0,SQLITE_BLOB,&length)==SQLITE_OK && length==size);
    assert(gq_integer(s,0,&value)==GQ_TYPE && value==0);
    uint8_t *bytes=malloc((size_t)size+2); assert(bytes);
    memset(bytes,0xa5,(size_t)size+2);
    if (size) {
        assert(gq_fetch(s,0,SQLITE_BLOB,(gq_output){bytes+1,size-1},&length)==GQ_LIMIT && length==size);
        for (int64_t i=0;i<size+2;++i) assert(bytes[i]==0xa5);
    }
    assert(gq_fetch(s,0,SQLITE_BLOB,(gq_output){bytes+1,size},&length)==SQLITE_OK && length==size);
    assert(bytes[0]==0xa5 && bytes[size+1]==0xa5);
    for (int64_t i=0;i<size;++i) assert(bytes[i+1]==0);
    assert(gq_bind_zeroblob(s,1,size)==GQ_STATE);
    assert(gq_step(s)==SQLITE_DONE && gq_bind_zeroblob(s,1,size)==GQ_STATE);
    assert(gq_reset(s)==SQLITE_OK);
    free(bytes); ++checked_values;
}
static void integer(uint64_t s,int64_t expected) {
    int64_t value=0;
    assert(gq_step(s)==SQLITE_ROW && gq_integer(s,0,&value)==SQLITE_OK && value==expected);
    assert(gq_step(s)==SQLITE_DONE && gq_reset(s)==SQLITE_OK);
}
static void *foreign(void *p) {
    uint64_t token=*(const uint64_t *)p;
    assert(gq_bind_zeroblob(token,1,9)==GQ_HANDLE);
    uint64_t d=open_db(),s=prepare(d,"SELECT ?1");
    assert(gq_bind_zeroblob(s,1,7)==SQLITE_OK); zeros(s,7);
    assert(gq_bind_zeroblob(token,1,0)==GQ_HANDLE);
    assert(gq_finalize(s)==SQLITE_OK && gq_close(d)==SQLITE_OK); return NULL;
}
static void binding_cases(uint64_t d) {
    uint64_t s=prepare(d,"SELECT ?1");
    int64_t sizes[]={0,1,4096,65536,MAX_VALUE,17,0};
    for (size_t i=0;i<sizeof sizes/sizeof *sizes;++i) {
        assert(gq_bind_zeroblob(s,1,sizes[i])==SQLITE_OK);
        zeros(s,sizes[i]); zeros(s,sizes[i]); /* Reset retains the binding. */
    }
    assert(gq_bind(s,1,SQLITE_INTEGER,77,0,text(""))==SQLITE_OK);
    int64_t bad_sizes[]={-1,INT64_MIN,MAX_VALUE+1,INT64_MAX};
    for (size_t i=0;i<sizeof bad_sizes/sizeof *bad_sizes;++i) {
        assert(gq_bind_zeroblob(s,1,bad_sizes[i])==GQ_INPUT); integer(s,77);
    }
    int64_t bad_indices[]={INT64_MIN,-1,0,2,INT64_MAX};
    for (size_t i=0;i<sizeof bad_indices/sizeof *bad_indices;++i) {
        assert(gq_bind_zeroblob(s,bad_indices[i],8)==GQ_INPUT); integer(s,77);
    }
    assert(gq_bind_zeroblob(0,1,8)==GQ_HANDLE && gq_bind_zeroblob(d,1,8)==GQ_HANDLE);
    pthread_t worker; assert(!pthread_create(&worker,NULL,foreign,&s));
    assert(!pthread_join(worker,NULL)); integer(s,77);
    assert(gq_bind_zeroblob(s,1,5)==SQLITE_OK && gq_clear(s)==SQLITE_OK);
    assert(gq_step(s)==SQLITE_ROW && gq_type(s,0)==SQLITE_NULL);
    int64_t n=123; assert(gq_size(s,0,SQLITE_BLOB,&n)==GQ_TYPE && n==0);
    assert(gq_bind_zeroblob(s,0,-1)==GQ_STATE);
    assert(gq_step(s)==SQLITE_DONE && gq_reset(s)==SQLITE_OK);
    uint64_t stale=s; assert(gq_finalize(s)==SQLITE_OK);
    s=prepare(d,"SELECT ?5"); assert(s!=stale && gq_parameter_count(s)==5);
    assert(gq_bind_zeroblob(stale,1,8)==GQ_HANDLE);
    /* Parameter count is the largest index; valid holes remain bindable. */
    assert(gq_bind_zeroblob(s,1,19)==SQLITE_OK && gq_bind_zeroblob(s,5,3)==SQLITE_OK);
    zeros(s,3); assert(gq_finalize(s)==SQLITE_OK);
}
static void reservation(uint64_t d) {
    assert(exec(d,"CREATE TABLE t(id INTEGER PRIMARY KEY,payload BLOB)")==SQLITE_OK);
    uint64_t s=prepare(d,"INSERT INTO t VALUES(1,?1)");
    assert(gq_bind_zeroblob(s,1,4096)==SQLITE_OK);
    assert(gq_step(s)==SQLITE_DONE && gq_finalize(s)==SQLITE_OK);
    s=prepare(d,"SELECT payload FROM t WHERE id=1"); zeros(s,4096);
    assert(gq_finalize(s)==SQLITE_OK);
    uint64_t b=123;
    assert(gq_blob_open(d,text("t"),text("payload"),1,1,&b)==GQ_STATE && b==0);
    assert(exec(d,"BEGIN IMMEDIATE")==SQLITE_OK);
    assert(gq_blob_open(d,text("t"),text("payload"),1,1,&b)==SQLITE_OK);
    uint8_t bytes[4096],patch[]={0x61,0,0xff,0x62};
    assert(gq_blob_read(b,0,(gq_output){bytes,sizeof bytes})==SQLITE_OK);
    for (size_t i=0;i<sizeof bytes;++i) assert(bytes[i]==0);
    assert(gq_blob_write(b,2047,(gq_input){patch,sizeof patch})==SQLITE_OK);
    assert(gq_blob_close(b)==SQLITE_OK && gq_blob_close(b)==GQ_HANDLE);
    assert(exec(d,"COMMIT")==SQLITE_OK);
    s=prepare(d,"SELECT payload FROM t WHERE id=1");
    assert(gq_step(s)==SQLITE_ROW);
    assert(gq_copy(s,0,SQLITE_BLOB,(gq_output){bytes,sizeof bytes})==SQLITE_OK);
    for (size_t i=0;i<sizeof bytes;++i) {
        uint8_t expected=i>=2047 && i<2047+sizeof patch ? patch[i-2047] : 0;
        assert(bytes[i]==expected);
    }
    assert(gq_step(s)==SQLITE_DONE && gq_finalize(s)==SQLITE_OK);
    /* A legal binding size does not promise space for an encoded row header. */
    s=prepare(d,"INSERT INTO t VALUES(2,?1)");
    assert(gq_bind_zeroblob(s,1,MAX_VALUE)==SQLITE_OK);
    int64_t rc=gq_step(s),final=gq_finalize(s);
    if (rc==SQLITE_DONE) {
        assert(final==SQLITE_OK && scalar(d,"SELECT count(*) FROM t")==2);
        s=prepare(d,"SELECT payload FROM t WHERE id=2"); zeros(s,MAX_VALUE);
        assert(gq_finalize(s)==SQLITE_OK);
    } else {
        assert((rc&255)==SQLITE_TOOBIG && (final&255)==SQLITE_TOOBIG);
        assert(scalar(d,"SELECT count(*) FROM t")==1);
    }
}
int main(void) {
    assert(gq_initialize()==SQLITE_OK);
    uint64_t d=open_db(); binding_cases(d); reservation(d);
    assert(gq_close(d)==SQLITE_OK);
    assert(sqlite3_shutdown()==SQLITE_OK && sqlite3_memory_used()==0);
    printf("{\"zeroblob_values_checked\":%d,\"foreign_thread_checks\":2,\"reservation_bytes\":4096}\n",checked_values);
    return 0;
}
