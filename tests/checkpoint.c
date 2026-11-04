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
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static int checkpoints, busy_checks, state_checks;
static gq_input text(const char *s) { return (gq_input){(const uint8_t *)s,(int64_t)strlen(s)}; }
static uint64_t open_db(const char *path,int readonly) {
    uint64_t d=0; assert(gq_open(text(path),readonly,0,1000000,&d)==SQLITE_OK); return d;
}
static uint64_t prepare(uint64_t d,const char *sql) {
    uint64_t s=0; assert(gq_prepare(d,text(sql),&s)==SQLITE_OK); return s;
}
static int64_t exec(uint64_t d,const char *sql) {
    uint64_t s=0; int64_t rc=gq_prepare(d,text(sql),&s); if (rc) return rc;
    rc=gq_step(s); int64_t final=gq_finalize(s); return rc==SQLITE_DONE ? final : rc;
}
static int fixed(void) {
    int n=sqlite3_libversion_number();
    return n>=3051003 || (n>=3050007 && n<3051000) || (n>=3044006 && n<3045000);
}
static void result(uint64_t d,int64_t mode,int64_t expected) {
    int64_t log=123,checkpointed=456;
    assert(gq_checkpoint(d,mode,&log,&checkpointed)==expected);
    assert(log==-1 && checkpointed==-1);
}
static void state(uint64_t d,int64_t mode) { result(d,mode,GQ_STATE); ++state_checks; }
static void counts(uint64_t d,int64_t mode,int64_t expected,int partial) {
    int64_t log=-99,checkpointed=-99;
    assert(gq_checkpoint(d,mode,&log,&checkpointed)==expected);
    assert(log>=0 && checkpointed>=0 && checkpointed<=log);
    if (partial) assert(log>checkpointed);
    else assert(log==checkpointed);
    ++checkpoints;
    if (expected==SQLITE_BUSY) ++busy_checks;
}
static void bytes_for(uint8_t bytes[256],int epoch) {
    for (int i=0;i<256;++i) bytes[i]=epoch ? (uint8_t)(i*17+epoch*31) : 0;
    if (epoch) { bytes[0]=0; bytes[255]=255; }
}
static void update(uint64_t d,int epoch) {
    uint8_t bytes[256]; bytes_for(bytes,epoch);
    uint64_t s=prepare(d,"UPDATE t SET epoch=?1,payload=?2 WHERE id=1");
    assert(gq_bind(s,1,SQLITE_INTEGER,epoch,0,text(""))==SQLITE_OK);
    assert(gq_bind(s,2,SQLITE_BLOB,0,0,(gq_input){bytes,sizeof bytes})==SQLITE_OK);
    assert(gq_step(s)==SQLITE_DONE && gq_finalize(s)==SQLITE_OK);
}
static void verify(uint64_t d,int epoch) {
    uint64_t s=prepare(d,"SELECT id,epoch,payload FROM t");
    int64_t id=0,actual=-1; uint8_t bytes[256],expected[256]; bytes_for(expected,epoch);
    assert(gq_step(s)==SQLITE_ROW);
    assert(gq_integer(s,0,&id)==SQLITE_OK && id==1);
    assert(gq_integer(s,1,&actual)==SQLITE_OK && actual==epoch);
    assert(gq_copy(s,2,SQLITE_BLOB,(gq_output){bytes,sizeof bytes})==SQLITE_OK);
    assert(!memcmp(bytes,expected,sizeof bytes));
    assert(gq_step(s)==SQLITE_DONE && gq_finalize(s)==SQLITE_OK);
}
static void verify_raw(const char *path,int epoch) {
    sqlite3 *d=NULL; sqlite3_stmt *s=NULL;
    assert(sqlite3_open_v2(path,&d,SQLITE_OPEN_READWRITE,NULL)==SQLITE_OK);
    assert(sqlite3_prepare_v2(d,"PRAGMA integrity_check",-1,&s,NULL)==SQLITE_OK);
    assert(sqlite3_step(s)==SQLITE_ROW);
    const unsigned char *integrity=sqlite3_column_text(s,0);
    assert(integrity && !strcmp((const char *)integrity,"ok"));
    assert(sqlite3_step(s)==SQLITE_DONE && sqlite3_finalize(s)==SQLITE_OK);
    assert(sqlite3_prepare_v2(d,"SELECT id,epoch,payload FROM t",-1,&s,NULL)==SQLITE_OK);
    assert(sqlite3_step(s)==SQLITE_ROW && sqlite3_column_type(s,0)==SQLITE_INTEGER && sqlite3_column_int64(s,0)==1);
    assert(sqlite3_column_type(s,1)==SQLITE_INTEGER && sqlite3_column_int64(s,1)==epoch);
    assert(sqlite3_column_type(s,2)==SQLITE_BLOB && sqlite3_column_bytes(s,2)==256);
    uint8_t expected[256]; bytes_for(expected,epoch);
    const void *bytes=sqlite3_column_blob(s,2);
    assert(bytes && !memcmp(bytes,expected,sizeof expected));
    assert(sqlite3_step(s)==SQLITE_DONE && sqlite3_finalize(s)==SQLITE_OK && sqlite3_close(d)==SQLITE_OK);
}
static void *foreign(void *p) {
    uint64_t d=*(const uint64_t *)p;
    for (int mode=0;mode<=3;++mode) result(d,mode,GQ_HANDLE);
    uint64_t own=open_db(":memory:",0);
    result(d,0,GQ_HANDLE); assert(gq_close(own)==SQLITE_OK);
    return NULL;
}
static void validation(void) {
    result(0,0,GQ_HANDLE);
    int64_t log=123,checkpointed=456;
    assert(gq_checkpoint(0,0,NULL,&checkpointed)==GQ_INPUT);
    assert(checkpointed==-1);
    assert(gq_checkpoint(0,0,&log,NULL)==GQ_INPUT);
    assert(log==-1);
    assert(gq_checkpoint(0,0,NULL,NULL)==GQ_INPUT);
    uint64_t d=open_db(":memory:",0),s=prepare(d,"SELECT ?1");
    assert(gq_bind(s,1,SQLITE_INTEGER,42,0,text(""))==SQLITE_OK);
    result(s,0,GQ_HANDLE);
    int64_t invalid[]={INT64_MIN,-1,4,INT64_MAX};
    for (size_t i=0;i<sizeof invalid/sizeof *invalid;++i) result(d,invalid[i],GQ_INPUT);
    uint8_t first[10],second[10]; memset(first,17,sizeof first); memset(second,23,sizeof second);
    assert(gq_checkpoint(d,0,first+1,second+1)==(fixed() ? SQLITE_OK : SQLITE_MISUSE));
    memcpy(&log,first+1,sizeof log); memcpy(&checkpointed,second+1,sizeof checkpointed);
    assert(log==-1 && checkpointed==-1 && first[0]==17 && first[9]==17 && second[0]==23 && second[9]==23);
    for (int mode=0;mode<=3;++mode) result(d,mode,fixed() ? SQLITE_OK : SQLITE_MISUSE);
    pthread_t t; assert(!pthread_create(&t,NULL,foreign,&d) && !pthread_join(t,NULL));
    /* Checkpoint neither steps, resets, clears bindings nor destroys idle children. */
    int64_t value=0; assert(gq_step(s)==SQLITE_ROW && gq_integer(s,0,&value)==SQLITE_OK && value==42);
    assert(gq_step(s)==SQLITE_DONE && gq_finalize(s)==SQLITE_OK);
    if (fixed()) {
        assert(exec(d,"CREATE TABLE t(id INTEGER PRIMARY KEY,epoch,payload)")==SQLITE_OK);
        assert(exec(d,"INSERT INTO t VALUES(1,0,zeroblob(256))")==SQLITE_OK);
        assert(exec(d,"BEGIN")==SQLITE_OK);
        for (int mode=0;mode<=3;++mode) state(d,mode);
        int64_t automatic=1; assert(gq_status(d,2,&automatic)==SQLITE_OK && !automatic);
        assert(exec(d,"ROLLBACK")==SQLITE_OK);
        s=prepare(d,"SELECT epoch FROM t"); assert(gq_step(s)==SQLITE_ROW);
        assert(gq_status(d,2,&automatic)==SQLITE_OK && automatic);
        for (int mode=0;mode<=3;++mode) state(d,mode);
        assert(gq_integer(s,0,&value)==SQLITE_OK && value==0);
        assert(gq_step(s)==SQLITE_DONE && gq_finalize(s)==SQLITE_OK);
        uint64_t b=0; assert(gq_blob_open(d,text("t"),text("payload"),1,0,&b)==SQLITE_OK);
        result(b,0,GQ_HANDLE);
        for (int mode=0;mode<=3;++mode) state(d,mode);
        uint8_t bytes[256]; assert(gq_blob_read(b,0,(gq_output){bytes,sizeof bytes})==SQLITE_OK);
        for (size_t i=0;i<sizeof bytes;++i) assert(bytes[i]==0);
        assert(gq_blob_close(b)==SQLITE_OK);
        for (int mode=0;mode<=3;++mode) result(d,mode,SQLITE_OK);
    }
    assert(gq_close(d)==SQLITE_OK);
    for (int mode=0;mode<=3;++mode) result(d,mode,GQ_HANDLE);
    uint64_t replacement=open_db(":memory:",0); assert(replacement!=d);
    result(d,0,GQ_HANDLE); assert(gq_close(replacement)==SQLITE_OK);
}
/* Pause a real SQLite FULL checkpoint in its busy handler while it owns the
   checkpoint lock and waits for the old snapshot. No connection crosses threads. */
typedef struct {
    pthread_mutex_t mutex;
    pthread_cond_t condition;
    struct timespec deadline;
    const char *path;
    int ready,release,calls,code,frames,copied;
} Competitor;
static int hold_checkpoint(void *p,int prior) {
    (void)prior; Competitor *c=p;
    assert(!pthread_mutex_lock(&c->mutex));
    ++c->calls; c->ready=1; assert(!pthread_cond_broadcast(&c->condition));
    while (!c->release) assert(!pthread_cond_timedwait(&c->condition,&c->mutex,&c->deadline));
    assert(!pthread_mutex_unlock(&c->mutex)); return 0;
}
static void *competing_checkpoint(void *p) {
    Competitor *c=p; sqlite3 *d=NULL; sqlite3_stmt *s=NULL;
    assert(sqlite3_open_v2(c->path,&d,SQLITE_OPEN_READWRITE|SQLITE_OPEN_NOMUTEX|SQLITE_OPEN_PRIVATECACHE,NULL)==SQLITE_OK);
    assert(sqlite3_prepare_v2(d,"SELECT count(*) FROM t",-1,&s,NULL)==SQLITE_OK);
    assert(sqlite3_step(s)==SQLITE_ROW && sqlite3_column_int64(s,0)==1);
    assert(sqlite3_step(s)==SQLITE_DONE && sqlite3_finalize(s)==SQLITE_OK);
    assert(sqlite3_busy_handler(d,hold_checkpoint,c)==SQLITE_OK);
    c->frames=-1; c->copied=-1;
    c->code=sqlite3_wal_checkpoint_v2(d,"main",SQLITE_CHECKPOINT_FULL,&c->frames,&c->copied);
    assert(sqlite3_close(d)==SQLITE_OK); return NULL;
}
static void checkpoint_lock_busy(const char *path,uint64_t checkpointer,uint64_t reader) {
    Competitor c={0}; c.path=path;
    assert(!clock_gettime(CLOCK_MONOTONIC,&c.deadline)); c.deadline.tv_sec+=30;
    assert(!pthread_mutex_init(&c.mutex,NULL));
    pthread_condattr_t attr; assert(!pthread_condattr_init(&attr));
    assert(!pthread_condattr_setclock(&attr,CLOCK_MONOTONIC));
    assert(!pthread_cond_init(&c.condition,&attr) && !pthread_condattr_destroy(&attr));
    pthread_t thread; assert(!pthread_create(&thread,NULL,competing_checkpoint,&c));
    assert(!pthread_mutex_lock(&c.mutex));
    while (!c.ready) assert(!pthread_cond_timedwait(&c.condition,&c.mutex,&c.deadline));
    assert(c.calls==1 && !pthread_mutex_unlock(&c.mutex));
    /* Unlike writer/reader contention, the checkpoint lock yields no counters. */
    result(checkpointer,SQLITE_CHECKPOINT_PASSIVE,SQLITE_BUSY); ++checkpoints; ++busy_checks;
    verify(reader,0);
    assert(!pthread_mutex_lock(&c.mutex)); c.release=1;
    assert(!pthread_cond_broadcast(&c.condition) && !pthread_mutex_unlock(&c.mutex));
    assert(!pthread_join(thread,NULL));
    assert(c.code==SQLITE_BUSY && c.frames>c.copied && c.copied>=0 && c.calls==1);
    assert(!pthread_cond_destroy(&c.condition) && !pthread_mutex_destroy(&c.mutex));
}
static void wal_tests(const char *path) {
    uint64_t writer=0;
    assert(gq_open_config(text(path),0,0,1000000,1,&writer)==SQLITE_OK);
    assert(exec(writer,"CREATE TABLE t(id INTEGER PRIMARY KEY,epoch,payload)")==SQLITE_OK);
    assert(exec(writer,"INSERT INTO t VALUES(1,0,zeroblob(256))")==SQLITE_OK);
    int64_t log=-1,checkpointed=-1;
    assert(gq_checkpoint(writer,SQLITE_CHECKPOINT_TRUNCATE,&log,&checkpointed)==SQLITE_OK && !log && !checkpointed);
    ++checkpoints;
    uint64_t reader=open_db(path,0);
    assert(exec(reader,"BEGIN")==SQLITE_OK); verify(reader,0);
    update(writer,1); verify(writer,1);
    /* No SQL/schema read is issued on this default-options connection before the
       first checkpoint. It must discover an existing WAL, not silently skip it. */
    uint64_t checkpointer=open_db(path,0);
    counts(checkpointer,SQLITE_CHECKPOINT_PASSIVE,SQLITE_OK,1);
    verify(reader,0); verify(writer,1);
    for (int mode=SQLITE_CHECKPOINT_FULL;mode<=SQLITE_CHECKPOINT_TRUNCATE;++mode) {
        counts(checkpointer,mode,SQLITE_BUSY,1); verify(reader,0); verify(writer,1);
    }
    checkpoint_lock_busy(path,checkpointer,reader); verify(reader,0); verify(writer,1);
    int64_t automatic=0;
    assert(gq_status(checkpointer,2,&automatic)==SQLITE_OK && automatic);
    assert(exec(reader,"COMMIT")==SQLITE_OK && gq_close(reader)==SQLITE_OK);
    counts(checkpointer,SQLITE_CHECKPOINT_FULL,SQLITE_OK,0);
    counts(checkpointer,SQLITE_CHECKPOINT_RESTART,SQLITE_OK,0);
    assert(gq_checkpoint(checkpointer,SQLITE_CHECKPOINT_TRUNCATE,&log,&checkpointed)==SQLITE_OK && !log && !checkpointed);
    ++checkpoints;
    char wal_path[512]; int n=snprintf(wal_path,sizeof wal_path,"%s-wal",path);
    assert(n>0 && (size_t)n<sizeof wal_path);
    struct stat st; assert(!stat(wal_path,&st) && st.st_size==0);
    verify(writer,1); verify(checkpointer,1);
    uint64_t readonly=open_db(path,1);
    for (int mode=0;mode<=3;++mode) result(readonly,mode,SQLITE_READONLY);
    assert(exec(readonly,"BEGIN")==SQLITE_OK);
    result(readonly,0,SQLITE_READONLY); /* Readonly policy precedes transaction state. */
    assert(exec(readonly,"ROLLBACK")==SQLITE_OK && gq_close(readonly)==SQLITE_OK);
    update(writer,2);
    uint64_t fresh=open_db(path,0);
    counts(fresh,SQLITE_CHECKPOINT_FULL,SQLITE_OK,0); verify(fresh,2);
    assert(exec(writer,"BEGIN IMMEDIATE")==SQLITE_OK);
    counts(fresh,SQLITE_CHECKPOINT_FULL,SQLITE_BUSY,0);
    assert(gq_status(writer,2,&automatic)==SQLITE_OK && !automatic);
    assert(exec(writer,"ROLLBACK")==SQLITE_OK);
    uint64_t idle=prepare(fresh,"SELECT ?1");
    assert(gq_bind(idle,1,SQLITE_INTEGER,97,0,text(""))==SQLITE_OK);
    counts(fresh,SQLITE_CHECKPOINT_PASSIVE,SQLITE_OK,0);
    int64_t value=0; assert(gq_step(idle)==SQLITE_ROW && gq_integer(idle,0,&value)==SQLITE_OK && value==97);
    assert(gq_step(idle)==SQLITE_DONE && gq_finalize(idle)==SQLITE_OK);
    assert(exec(fresh,"PRAGMA wal_checkpoint(TRUNCATE)")==SQLITE_AUTH);
    assert(gq_close(fresh)==SQLITE_OK && gq_close(checkpointer)==SQLITE_OK && gq_close(writer)==SQLITE_OK);
    verify_raw(path,2);
}
int main(int argc,char **argv) {
    int require=argc==2 && !strcmp(argv[1],"--require-wal"); assert(argc==1 || require);
    validation();
    char dir[]="/tmp/goose-checkpoint-XXXXXX"; assert(mkdtemp(dir));
    char path[512]; int n=snprintf(path,sizeof path,"%s/main.db",dir); assert(n>0 && (size_t)n<sizeof path);
    if (fixed()) { wal_tests(path); assert(!unlink(path)); }
    else assert(!require);
    assert(!rmdir(dir));
    printf("{\"wal_supported\":%s,\"checkpoints\":%d,\"busy_checks\":%d,\"state_checks\":%d}\n",fixed() ? "true":"false",checkpoints,busy_checks,state_checks);
    assert(sqlite3_shutdown()==SQLITE_OK && sqlite3_memory_used()==0);
    return 0;
}
