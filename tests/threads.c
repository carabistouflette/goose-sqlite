/* SPDX-License-Identifier: Apache-2.0 */
#define _POSIX_C_SOURCE 200809L
#include "../native/sqlite.h"
#include <sqlite3.h>
#include <pthread.h>
#include <stdatomic.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define THREADS 8
#define WAVES 8
#define LOOPS 16
#define WRITERS 4
#define WRITES 64
static pthread_barrier_t barrier;
typedef struct { uint64_t db,stmt,blob; } Tokens;
static Tokens live[THREADS],previous[THREADS];
static uint64_t minted[WAVES*THREADS*LOOPS*3];
typedef struct { int id,wave; const char *path; } Work;
static atomic_int cleanups,committed,writers_left;
static atomic_int busy_count,read_count;
static gq_input text(const char *s) { return (gq_input){(const uint8_t *)s,(int64_t)strlen(s)}; }
static void sync_all(void) { int rc=pthread_barrier_wait(&barrier); assert(rc==0 || rc==PTHREAD_BARRIER_SERIAL_THREAD); }
static int64_t exec(uint64_t d,const char *sql) {
    uint64_t s=0; int64_t rc=gq_prepare(d,text(sql),&s); if (rc) return rc;
    rc=gq_step(s); int64_t done=gq_finalize(s); return rc==SQLITE_DONE ? done : rc;
}
static uint64_t open_db(const char *p) { uint64_t d=0; assert(gq_open(text(p),0,0,1000000,&d)==SQLITE_OK); return d; }
static uint64_t prepare(uint64_t d,const char *sql) { uint64_t s=0; assert(gq_prepare(d,text(sql),&s)==SQLITE_OK); return s; }
static int64_t scalar(uint64_t d,const char *sql) {
    uint64_t s=prepare(d,sql); int64_t value=0;
    assert(gq_step(s)==SQLITE_ROW && gq_integer(s,0,&value)==SQLITE_OK);
    assert(gq_step(s)==SQLITE_DONE && gq_finalize(s)==SQLITE_OK); return value;
}
static void reject(Tokens t) {
    int64_t value=123;
    assert(gq_close(t.db)==GQ_HANDLE && gq_finalize(t.stmt)==GQ_HANDLE);
    assert(gq_blob_size(t.blob,&value)==GQ_HANDLE && value==0);
    value=123; assert(gq_stmt_status(t.stmt,SQLITE_STMTSTATUS_RUN,0,&value)==GQ_HANDLE && value==0);
}
static void *churn(void *p) {
    Work *w=p; sync_all(); /* First wave races the first-ever wrapper open. */
    for (int i=0;i<LOOPS;++i) {
        Tokens t={0}; t.db=open_db(":memory:");
        assert(exec(t.db,"CREATE TABLE t(x)")==SQLITE_OK);
        assert(exec(t.db,"INSERT INTO t VALUES(zeroblob(8))")==SQLITE_OK);
        t.stmt=prepare(t.db,"SELECT 7");
        assert(gq_blob_open(t.db,text("t"),text("x"),1,0,&t.blob)==SQLITE_OK);
        live[w->id]=t; size_t off=((size_t)w->wave*THREADS+w->id)*LOOPS*3+(size_t)i*3;
        minted[off]=t.db; minted[off+1]=t.stmt; minted[off+2]=t.blob;
        sync_all(); reject(live[(w->id+1)%THREADS]);
        if (w->wave) reject(previous[w->id]);
        int64_t value=0; uint8_t bytes[8];
        assert(gq_step(t.stmt)==SQLITE_ROW && gq_integer(t.stmt,0,&value)==SQLITE_OK && value==7);
        assert(gq_blob_read(t.blob,0,(gq_output){bytes,8})==SQLITE_OK);
        for (int j=0;j<8;++j) assert(bytes[j]==0);
        sync_all(); /* No owner destroys a handle until all foreign checks finish. */
        assert(gq_finalize(t.stmt)==SQLITE_OK && gq_blob_close(t.blob)==SQLITE_OK && gq_close(t.db)==SQLITE_OK);
        reject(t);
    }
    return NULL;
}
static int token_order(const void *a,const void *b) { uint64_t x=*(const uint64_t *)a,y=*(const uint64_t *)b; return (x>y)-(x<y); }
static void churn_phase(void) {
    for (int wave=0;wave<WAVES;++wave) {
        pthread_t t[THREADS]; Work w[THREADS]; assert(pthread_barrier_init(&barrier,NULL,THREADS)==0);
        for (int i=0;i<THREADS;++i) { w[i]=(Work){i,wave,NULL}; assert(!pthread_create(&t[i],NULL,churn,&w[i])); }
        for (int i=0;i<THREADS;++i) assert(!pthread_join(t[i],NULL));
        memcpy(previous,live,sizeof live); assert(!pthread_barrier_destroy(&barrier));
    }
    qsort(minted,sizeof minted/sizeof *minted,sizeof *minted,token_order);
    assert(minted[0]); for (size_t i=1;i<sizeof minted/sizeof *minted;++i) assert(minted[i]!=minted[i-1]);
}
/* Registered once outside concurrent work. Callback state is per OS thread. */
typedef struct { uint64_t token; } Cleanup;
static _Thread_local Cleanup *context;
static _Thread_local int reentering;
static void noop(sqlite3_context *c,int n,sqlite3_value **v) { (void)n;(void)v;sqlite3_result_null(c); }
static void cleanup(void *p) {
    Cleanup *c=p;
    if (context==c) context=NULL;
    if (!c->token || reentering) { free(c); return; }
    reentering=1; context=NULL; int64_t value=123;
    assert(gq_status(c->token,2,&value)==GQ_HANDLE && value==0);
    uint64_t fresh=open_db(":memory:"); assert(scalar(fresh,"SELECT 13")==13 && gq_close(fresh)==SQLITE_OK);
    atomic_fetch_add(&cleanups,1); free(c); reentering=0;
}
static int extension(sqlite3 *d,char **error,const sqlite3_api_routines *api) {
    (void)error;(void)api; if (reentering) return SQLITE_OK;
    Cleanup *c=calloc(1,sizeof *c); if (!c) return SQLITE_NOMEM;
    int rc=sqlite3_create_function_v2(d,"test_thread_cleanup",0,SQLITE_UTF8,c,noop,NULL,NULL,cleanup);
    if (rc==SQLITE_OK) context=c;
    return rc;
}
static void path_for(char *out,size_t n,const char *dir,int wave,int id) {
    int used=snprintf(out,n,"%s/exit-%d-%d.db",dir,wave,id); assert(used>0 && (size_t)used<n);
}
static void *abandon(void *p) {
    Work *w=p; char path[512]; path_for(path,sizeof path,w->path,w->wave,w->id);
    sync_all(); uint64_t d=open_db(path); assert(context); context->token=d;
    assert(exec(d,"BEGIN IMMEDIATE")==SQLITE_OK);
    uint64_t b=0; assert(gq_blob_open(d,text("t"),text("x"),1,1,&b)==SQLITE_OK);
    assert(gq_blob_write(b,0,text("changed"))==SQLITE_OK);
    uint64_t s=prepare(d,"SELECT x FROM t"); assert(gq_step(s)==SQLITE_ROW);
    return NULL; /* Key destructor must close all three resources and roll back. */
}
static void teardown_phase(const char *dir) {
    assert(sqlite3_auto_extension((void (*)(void))extension)==SQLITE_OK);
    for (int wave=0;wave<WAVES;++wave) {
        /* Raw fixtures are closed before workers start; no copied live WAL files. */
        for (int i=0;i<THREADS;++i) {
            char path[512]; path_for(path,sizeof path,dir,wave,i); sqlite3 *d=NULL;
            assert(sqlite3_open(path,&d)==SQLITE_OK);
            assert(sqlite3_exec(d,"CREATE TABLE t(x); INSERT INTO t VALUES(zeroblob(32))",NULL,NULL,NULL)==SQLITE_OK);
            assert(sqlite3_close(d)==SQLITE_OK);
        }
        pthread_t t[THREADS]; Work w[THREADS]; assert(!pthread_barrier_init(&barrier,NULL,THREADS));
        for (int i=0;i<THREADS;++i) { w[i]=(Work){i,wave,dir}; assert(!pthread_create(&t[i],NULL,abandon,&w[i])); }
        for (int i=0;i<THREADS;++i) assert(!pthread_join(t[i],NULL));
        assert(!pthread_barrier_destroy(&barrier));
        for (int i=0;i<THREADS;++i) {
            char path[512]; path_for(path,sizeof path,dir,wave,i); uint64_t d=open_db(path);
            /* Main-thread hooks have token0 and cannot re-enter on close. */
            assert(scalar(d,"SELECT x=zeroblob(32) FROM t")==1 && gq_close(d)==SQLITE_OK);
            context=NULL; assert(!unlink(path));
        }
    }
    sqlite3_reset_auto_extension(); assert(atomic_load(&cleanups)==WAVES*THREADS);
}
static int64_t monotonic_ms(void) { struct timespec t; assert(!clock_gettime(CLOCK_MONOTONIC,&t)); return (int64_t)t.tv_sec*1000+t.tv_nsec/1000000; }
static void pause_briefly(void) { struct timespec t={0,1000000}; nanosleep(&t,NULL); }
static void bytes_for(uint8_t *out,int worker,int seq) { memset(out,(worker*31+seq)%251,32);out[0]=0;out[31]=255; }
static void rollback(uint64_t d) { int64_t auto_mode=0;assert(gq_status(d,2,&auto_mode)==SQLITE_OK);if (!auto_mode) assert(exec(d,"ROLLBACK")==SQLITE_OK); }
static void *writer(void *p) {
    Work *w=p; uint64_t d=open_db(w->path),s=prepare(d,"INSERT INTO items VALUES(?1,?2,?3,?4)");sync_all();
    int64_t deadline=monotonic_ms()+30000;
    for (int seq=0;seq<WRITES;++seq) {
        int done=0;
        for (int attempt=0;attempt<10000 && monotonic_ms()<deadline;++attempt) {
            int64_t rc=exec(d,"BEGIN IMMEDIATE");
            if (rc==SQLITE_OK) {
                uint8_t bytes[32];bytes_for(bytes,w->id,seq);
                assert(gq_bind(s,1,SQLITE_INTEGER,w->id*WRITES+seq,0,text(""))==SQLITE_OK);
                assert(gq_bind(s,2,SQLITE_INTEGER,w->id,0,text(""))==SQLITE_OK);
                assert(gq_bind(s,3,SQLITE_INTEGER,seq,0,text(""))==SQLITE_OK);
                assert(gq_bind(s,4,SQLITE_BLOB,0,0,(gq_input){bytes,32})==SQLITE_OK);
                rc=gq_step(s); int64_t reset=gq_reset(s);
                if (rc==SQLITE_DONE) { assert(reset==SQLITE_OK);rc=exec(d,"COMMIT"); }
                else assert(reset==rc);
            }
            if (rc==SQLITE_OK) { atomic_fetch_add(&committed,1);done=1;break; }
            assert(rc>0 && (rc&255)==SQLITE_BUSY);atomic_fetch_add(&busy_count,1);rollback(d);pause_briefly();
        }
        assert(done);
    }
    assert(gq_finalize(s)==SQLITE_OK && gq_close(d)==SQLITE_OK);atomic_fetch_sub(&writers_left,1);return NULL;
}
static void *reader(void *p) {
    Work *w=p;uint64_t d=open_db(w->path);sync_all();int loops=0;int64_t deadline=monotonic_ms()+30000;
    while (atomic_load(&writers_left) || loops<32) {
        assert(++loops<=10000 && monotonic_ms()<deadline);
        assert(exec(d,"BEGIN")==SQLITE_OK);
        uint64_t s=prepare(d,"SELECT id,worker,seq,payload FROM items ORDER BY id");
        int64_t count=0,sum=0,rc;
        while ((rc=gq_step(s))==SQLITE_ROW) {
            int64_t id=0,worker=0,seq=0;uint8_t out[32],expected[32];
            assert(gq_integer(s,0,&id)==SQLITE_OK && gq_integer(s,1,&worker)==SQLITE_OK && gq_integer(s,2,&seq)==SQLITE_OK);
            assert(worker>=0 && worker<WRITERS && seq>=0 && seq<WRITES && id==worker*WRITES+seq);
            bytes_for(expected,(int)worker,(int)seq);assert(gq_copy(s,3,SQLITE_BLOB,(gq_output){out,32})==SQLITE_OK && !memcmp(out,expected,32));
            ++count;sum+=id;
        }
        assert(rc==SQLITE_DONE && gq_finalize(s)==SQLITE_OK);pause_briefly();
        assert(scalar(d,"SELECT count(*) FROM items")==count && scalar(d,"SELECT coalesce(sum(id),0) FROM items")==sum);
        assert(exec(d,"COMMIT")==SQLITE_OK);atomic_fetch_add(&read_count,1);
    }
    assert(gq_close(d)==SQLITE_OK);return NULL;
}
static void *contended(void *p) { uint64_t d=open_db(p);assert(exec(d,"BEGIN IMMEDIATE")==SQLITE_BUSY);assert(gq_close(d)==SQLITE_OK);return NULL; }
static void *snapshot_writer(void *p) { uint64_t d=open_db(p);assert(exec(d,"INSERT INTO items VALUES(-1,-1,-1,x'00')")==SQLITE_OK && gq_close(d)==SQLITE_OK);return NULL; }
static int wal_phase(const char *dir) {
    char path[512];int n=snprintf(path,sizeof path,"%s/wal.db",dir);assert(n>0 && n<(int)sizeof path);
    uint64_t d=0;int64_t rc=gq_open_config(text(path),0,0,1000000,1,&d);
    if (rc==SQLITE_MISUSE) { assert(d==0);return 0; }assert(rc==SQLITE_OK);
    assert(exec(d,"CREATE TABLE items(id INTEGER PRIMARY KEY,worker,seq,payload)")==SQLITE_OK);
    pthread_t t;assert(exec(d,"BEGIN IMMEDIATE")==SQLITE_OK);
    assert(!pthread_create(&t,NULL,contended,path) && !pthread_join(t,NULL));assert(exec(d,"ROLLBACK")==SQLITE_OK);
    assert(exec(d,"BEGIN")==SQLITE_OK && scalar(d,"SELECT count(*) FROM items")==0);
    assert(!pthread_create(&t,NULL,snapshot_writer,path) && !pthread_join(t,NULL));
    assert(scalar(d,"SELECT count(*) FROM items")==0 && exec(d,"COMMIT")==SQLITE_OK && scalar(d,"SELECT count(*) FROM items")==1);
    assert(exec(d,"DELETE FROM items")==SQLITE_OK);
    pthread_t workers[THREADS];Work w[THREADS];atomic_store(&writers_left,WRITERS);assert(!pthread_barrier_init(&barrier,NULL,THREADS));
    for (int i=0;i<THREADS;++i) {w[i]=(Work){i,0,path};assert(!pthread_create(&workers[i],NULL,i<WRITERS ? writer : reader,&w[i]));}
    for (int i=0;i<THREADS;++i) assert(!pthread_join(workers[i],NULL));
    assert(!pthread_barrier_destroy(&barrier));
    int total=WRITERS*WRITES;assert(atomic_load(&committed)==total && scalar(d,"SELECT count(*) FROM items")==total);
    assert(scalar(d,"SELECT sum(id) FROM items")==(int64_t)total*(total-1)/2);
    Work final={0,0,path};atomic_store(&writers_left,0);
    /* reader needs its barrier; main supplies a one-participant verification pass. */
    assert(!pthread_barrier_init(&barrier,NULL,1));reader(&final);assert(!pthread_barrier_destroy(&barrier));
    assert(gq_close(d)==SQLITE_OK && !unlink(path));return 1;
}
int main(int argc,char **argv) {
    if (argc==2 && !strcmp(argv[1],"identity")) {
        printf("{\"version\":\"%s\",\"source_id\":\"%s\"}\n",sqlite3_libversion(),sqlite3_sourceid());return 0;
    }
    int serial_init=argc==2 && !strcmp(argv[1],"--initialize-engine");
    assert(argc==1 || serial_init);
    /* Keep first wrapper/key initialization concurrent. The TSan run separately
       initializes SQLite to exclude its engine isInit fastpath report. Ordinary
       ASan/UBSan runs retain the fully concurrent cold engine start. */
    if (serial_init) assert(sqlite3_initialize()==SQLITE_OK);
    char dir[]="/tmp/goose-threads-XXXXXX";assert(mkdtemp(dir));
    churn_phase(); /* No main-thread gq call may precede this phase. */
    teardown_phase(dir);int wal=wal_phase(dir);
    if (!wal) { char path[512];snprintf(path,sizeof path,"%s/wal.db",dir);assert(unlink(path)==0 || access(path,F_OK)!=0); }
    assert(!rmdir(dir));
    printf("{\"threads\":%d,\"waves\":%d,\"registry_cycles\":%d,\"unique_tokens\":%zu,\"cleanup_callbacks\":%d,\"engine_preinitialized\":%s,\"wal\":%s,\"committed\":%d,\"reader_snapshots\":%d,\"busy_retries\":%d}\n",THREADS,WAVES,THREADS*WAVES*LOOPS,sizeof minted/sizeof *minted,atomic_load(&cleanups),serial_init ? "true":"false",wal ? "true":"false",atomic_load(&committed),atomic_load(&read_count),atomic_load(&busy_count));
    assert(sqlite3_shutdown()==SQLITE_OK && sqlite3_memory_used()==0);return 0;
}
