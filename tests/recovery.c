/* SPDX-License-Identifier: Apache-2.0 */
#define _POSIX_C_SOURCE 200809L
#include "../native/sqlite.h"
#include <sqlite3.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Test-only, single-threaded forwarding VFS. No production injection hooks. */
typedef struct { sqlite3_file file; sqlite3_file *real; sqlite3_io_methods methods; } File;
static sqlite3_vfs *base, shim;
static int armed, cut, seen, fired, sticky, sync_fault, full_fault, crash_fault;
static int phase, first_fault_phase;
static int fault(void) {
    if (!armed) return 0;
    ++seen;
    if (seen < cut || (fired && !sticky)) return 0;
    if (!fired) first_fault_phase=phase;
    ++fired;
    if (crash_fault) _exit(write(STDOUT_FILENO,"crash\n",6)==6 ? 86 : 88); /* Process crash before the OS call, not power loss. */
    return 1;
}
static File *file(sqlite3_file *f) { return (File *)f; }
static int close_file(sqlite3_file *f) {
    File *p=file(f); int rc=p->real->pMethods->xClose(p->real);
    sqlite3_free(p->real); p->real=NULL; f->pMethods=NULL; return rc;
}
static int write_file(sqlite3_file *f,const void *p,int n,sqlite3_int64 off) {
    if (!sync_fault && fault()) return full_fault ? SQLITE_FULL : SQLITE_IOERR_WRITE;
    File *x=file(f); return x->real->pMethods->xWrite(x->real,p,n,off);
}
static int sync_file(sqlite3_file *f,int flags) {
    if (sync_fault && fault()) return SQLITE_IOERR_FSYNC;
    File *x=file(f); return x->real->pMethods->xSync(x->real,flags);
}
#define FORWARD(name, member, params, args) static int name params { File *x=file(f); return x->real->pMethods->member args; }
FORWARD(read_file,xRead,(sqlite3_file *f,void *p,int n,sqlite3_int64 off),(x->real,p,n,off))
FORWARD(truncate_file,xTruncate,(sqlite3_file *f,sqlite3_int64 n),(x->real,n))
FORWARD(size_file,xFileSize,(sqlite3_file *f,sqlite3_int64 *n),(x->real,n))
FORWARD(lock_file,xLock,(sqlite3_file *f,int n),(x->real,n))
FORWARD(unlock_file,xUnlock,(sqlite3_file *f,int n),(x->real,n))
FORWARD(reserved_file,xCheckReservedLock,(sqlite3_file *f,int *n),(x->real,n))
FORWARD(control_file,xFileControl,(sqlite3_file *f,int op,void *p),(x->real,op,p))
FORWARD(sector_file,xSectorSize,(sqlite3_file *f),(x->real))
FORWARD(device_file,xDeviceCharacteristics,(sqlite3_file *f),(x->real))
FORWARD(map_file,xShmMap,(sqlite3_file *f,int i,int n,int w,void volatile **p),(x->real,i,n,w,p))
FORWARD(shm_lock,xShmLock,(sqlite3_file *f,int i,int n,int flags),(x->real,i,n,flags))
FORWARD(unmap_file,xShmUnmap,(sqlite3_file *f,int del),(x->real,del))
FORWARD(fetch_file,xFetch,(sqlite3_file *f,sqlite3_int64 off,int n,void **p),(x->real,off,n,p))
FORWARD(unfetch_file,xUnfetch,(sqlite3_file *f,sqlite3_int64 off,void *p),(x->real,off,p))
static void barrier_file(sqlite3_file *f) { File *x=file(f); x->real->pMethods->xShmBarrier(x->real); }
static const sqlite3_io_methods methods={3,close_file,read_file,write_file,truncate_file,sync_file,size_file,lock_file,unlock_file,reserved_file,control_file,sector_file,device_file,map_file,shm_lock,barrier_file,unmap_file,fetch_file,unfetch_file};
static int open_file(sqlite3_vfs *v,const char *name,sqlite3_file *out,int flags,int *actual) {
    (void)v; File *p=file(out); out->pMethods=NULL;
    p->real=sqlite3_malloc(base->szOsFile); if (!p->real) return SQLITE_NOMEM;
    memset(p->real,0,(size_t)base->szOsFile);
    int rc=base->xOpen(base,name,p->real,flags,actual);
    if (rc!=SQLITE_OK || !p->real->pMethods) {
        if (p->real->pMethods) p->real->pMethods->xClose(p->real);
        sqlite3_free(p->real); p->real=NULL; return rc==SQLITE_OK ? SQLITE_CANTOPEN : rc;
    }
    p->methods=methods;
    const sqlite3_io_methods *m=p->real->pMethods;
    p->methods.iVersion=m->iVersion<3 ? m->iVersion : 3;
    if (m->iVersion<2 || !m->xShmMap) p->methods.xShmMap=NULL;
    if (m->iVersion<2 || !m->xShmLock) p->methods.xShmLock=NULL;
    if (m->iVersion<2 || !m->xShmBarrier) p->methods.xShmBarrier=NULL;
    if (m->iVersion<2 || !m->xShmUnmap) p->methods.xShmUnmap=NULL;
    if (m->iVersion<3 || !m->xFetch) p->methods.xFetch=NULL;
    if (m->iVersion<3 || !m->xUnfetch) p->methods.xUnfetch=NULL;
    out->pMethods=&p->methods; return SQLITE_OK;
}
/* Every VFS callback receives the original parent pointer. */
static int delete_file(sqlite3_vfs *v,const char *p,int sync) { (void)v; return base->xDelete(base,p,sync); }
static int access_file(sqlite3_vfs *v,const char *p,int flags,int *out) { (void)v; return base->xAccess(base,p,flags,out); }
static int pathname(sqlite3_vfs *v,const char *p,int n,char *out) { (void)v; return base->xFullPathname(base,p,n,out); }
static void *dlopen_vfs(sqlite3_vfs *v,const char *p) { (void)v; return base->xDlOpen(base,p); }
static void dlerror_vfs(sqlite3_vfs *v,int n,char *out) { (void)v; base->xDlError(base,n,out); }
static void (*dlsym_vfs(sqlite3_vfs *v,void *h,const char *p))(void) { (void)v; return base->xDlSym(base,h,p); }
static void dlclose_vfs(sqlite3_vfs *v,void *h) { (void)v; base->xDlClose(base,h); }
static int randomness(sqlite3_vfs *v,int n,char *out) { (void)v; return base->xRandomness(base,n,out); }
static int sleep_vfs(sqlite3_vfs *v,int n) { (void)v; return base->xSleep(base,n); }
static int time_vfs(sqlite3_vfs *v,double *out) { (void)v; return base->xCurrentTime(base,out); }
static int last_error(sqlite3_vfs *v,int n,char *out) { (void)v; return base->xGetLastError(base,n,out); }
static int time64(sqlite3_vfs *v,sqlite3_int64 *out) { (void)v; return base->xCurrentTimeInt64(base,out); }
static void install(void) {
    base=sqlite3_vfs_find(NULL); assert(base && base->iVersion>=2);
    memset(&shim,0,sizeof shim); shim.iVersion=2; shim.szOsFile=sizeof(File);
    shim.mxPathname=base->mxPathname; shim.zName="goose-recovery-test";
    shim.xOpen=open_file; shim.xDelete=delete_file; shim.xAccess=access_file;
    shim.xFullPathname=pathname; shim.xDlOpen=dlopen_vfs; shim.xDlError=dlerror_vfs;
    shim.xDlSym=dlsym_vfs; shim.xDlClose=dlclose_vfs; shim.xRandomness=randomness;
    shim.xSleep=sleep_vfs; shim.xCurrentTime=time_vfs; shim.xGetLastError=last_error;
    shim.xCurrentTimeInt64=base->xCurrentTimeInt64 ? time64 : NULL; assert(sqlite3_vfs_register(&shim,1)==SQLITE_OK);
}
static gq_input text(const char *s) { return (gq_input){(const uint8_t *)s,(int64_t)strlen(s)}; }
static int64_t exec(uint64_t d,const char *sql) {
    uint64_t s=0; int64_t rc=gq_prepare(d,text(sql),&s); if (rc) return rc;
    rc=gq_step(s); int64_t final=gq_finalize(s); return rc==SQLITE_DONE ? final : rc;
}
static int cache(sqlite3 *db,char **error,const sqlite3_api_routines *api) {
    (void)error; (void)api; return sqlite3_exec(db,"PRAGMA cache_size=8",NULL,NULL,NULL);
}
static void fixture(const char *path,int epoch) {
    sqlite3 *db=NULL; assert(sqlite3_open(path,&db)==SQLITE_OK);
    assert(sqlite3_exec(db,"PRAGMA page_size=4096; CREATE TABLE t(id INTEGER PRIMARY KEY,epoch,data); BEGIN",NULL,NULL,NULL)==SQLITE_OK);
    sqlite3_stmt *s=NULL; assert(sqlite3_prepare_v2(db,"INSERT INTO t VALUES(?1,?2,?3)",-1,&s,NULL)==SQLITE_OK);
    uint8_t bytes[32768]; memset(bytes,epoch ? 'b' : 0,sizeof bytes);
    for (int i=1;i<=4;++i) {
        assert(sqlite3_bind_int(s,1,i)==SQLITE_OK && sqlite3_bind_int(s,2,epoch)==SQLITE_OK);
        assert(sqlite3_bind_blob(s,3,bytes,sizeof bytes,SQLITE_TRANSIENT)==SQLITE_OK);
        assert(sqlite3_step(s)==SQLITE_DONE && sqlite3_reset(s)==SQLITE_OK);
    }
    assert(sqlite3_finalize(s)==SQLITE_OK && sqlite3_exec(db,"COMMIT",NULL,NULL,NULL)==SQLITE_OK);
    assert(sqlite3_close(db)==SQLITE_OK);
}
static int verify(const char *path) {
    sqlite3 *db=NULL; assert(sqlite3_open_v2(path,&db,SQLITE_OPEN_READWRITE,NULL)==SQLITE_OK);
    sqlite3_stmt *s=NULL; assert(sqlite3_prepare_v2(db,"PRAGMA integrity_check",-1,&s,NULL)==SQLITE_OK);
    assert(sqlite3_step(s)==SQLITE_ROW && !strcmp((const char *)sqlite3_column_text(s,0),"ok"));
    assert(sqlite3_step(s)==SQLITE_DONE && sqlite3_finalize(s)==SQLITE_OK);
    assert(sqlite3_prepare_v2(db,"SELECT id,epoch,data FROM t ORDER BY id",-1,&s,NULL)==SQLITE_OK);
    int epoch=-1;
    for (int i=1;i<=4;++i) {
        assert(sqlite3_step(s)==SQLITE_ROW && sqlite3_column_int(s,0)==i);
        assert(sqlite3_column_type(s,0)==SQLITE_INTEGER && sqlite3_column_int64(s,0)==i);
        assert(sqlite3_column_type(s,1)==SQLITE_INTEGER);
        sqlite3_int64 e=sqlite3_column_int64(s,1); assert(e==0 || e==1);
        if (epoch<0) epoch=e;
        assert(e==epoch);
        assert(sqlite3_column_type(s,2)==SQLITE_BLOB && sqlite3_column_bytes(s,2)==32768);
        const uint8_t *p=sqlite3_column_blob(s,2); assert(p);
        for (int j=0;j<32768;++j) assert(p[j]==(epoch ? 'b' : 0));
    }
    assert(sqlite3_step(s)==SQLITE_DONE && sqlite3_finalize(s)==SQLITE_OK);
    assert(sqlite3_close(db)==SQLITE_OK); return epoch;
}
int main(int argc,char **argv) {
    if (argc==2 && !strcmp(argv[1],"identity")) {
        printf("{\"version\":\"%s\",\"source_id\":\"%s\"}\n",sqlite3_libversion(),sqlite3_sourceid()); return 0;
    }
    assert(argc==8);
    const char *scenario=argv[2], *mode=argv[4]; int wal=atoi(argv[3]);
    cut=atoi(argv[5]); sticky=atoi(argv[6]); int expected=atoi(argv[7]);
    assert(cut>=0 && cut<=10000 && (sticky==0 || sticky==1));
    char dest[4096],src[4096];
    int n=snprintf(dest,sizeof dest,"%s/dest.db",argv[1]); assert(n>0 && n<(int)sizeof dest);
    n=snprintf(src,sizeof src,"%s/src.db",argv[1]); assert(n>0 && n<(int)sizeof src);
    if (!strcmp(mode,"verify")) {
        int epoch=verify(dest); assert(expected<0 || epoch==expected);
        if (!strcmp(scenario,"backup")) assert(verify(src)==1);
        printf("{\"epoch\":%d}\n",epoch); return 0;
    }
    fixture(dest,0); if (!strcmp(scenario,"backup")) fixture(src,1);
    install(); assert(sqlite3_auto_extension((void (*)(void))cache)==SQLITE_OK);
    uint64_t d=0,source=0;
    int64_t rc=gq_open_config(text(dest),0,0,1000000,wal,&d);
    if (wal && rc==SQLITE_MISUSE) { puts("{\"skipped\":true}"); return 0; }
    assert(rc==SQLITE_OK && d); sqlite3_reset_auto_extension();
    if (!strcmp(scenario,"backup")) assert(gq_open(text(src),0,0,1000000,&source)==SQLITE_OK);
    sync_fault=strstr(mode,"sync")!=NULL; full_fault=!strcmp(mode,"full");
    crash_fault=strncmp(mode,"crash-",6)==0;
    armed=strcmp(mode,"crash-after-ack")!=0; if (!cut) cut=10000;
    phase=4;
    if (!strcmp(scenario,"backup")) rc=gq_backup(source,d,1000);
    else {
        phase=0; rc=exec(d,"BEGIN IMMEDIATE");
        uint8_t bytes[32768]; memset(bytes,'b',sizeof bytes);
        if (!strcmp(scenario,"commit") && rc==SQLITE_OK) {
            phase=1; uint64_t s=0; rc=gq_prepare(d,text("UPDATE t SET epoch=1,data=?1"),&s);
            if (rc==SQLITE_OK) {
                rc=gq_bind(s,1,SQLITE_BLOB,0,0,(gq_input){bytes,sizeof bytes});
                if (rc==SQLITE_OK) { rc=gq_step(s); if (rc==SQLITE_DONE) rc=SQLITE_OK; }
                int64_t final=gq_finalize(s); if (rc==SQLITE_OK) rc=final;
                assert(gq_finalize(s)==GQ_HANDLE);
            }
        } else if (!strcmp(scenario,"blob")) {
            for (int i=1;i<=4 && rc==SQLITE_OK;++i) {
                phase=5; uint64_t b=0; rc=gq_blob_open(d,text("t"),text("data"),i,1,&b);
                if (rc==SQLITE_OK) {
                    phase=2; rc=gq_blob_write(b,0,(gq_input){bytes,sizeof bytes});
                    phase=5; int64_t final=gq_blob_close(b); if (rc==SQLITE_OK) rc=final;
                    assert(gq_blob_close(b)==GQ_HANDLE);
                }
            }
            if (rc==SQLITE_OK) { phase=5; rc=exec(d,"UPDATE t SET epoch=1"); }
        } else assert(!strcmp(scenario,"commit"));
        if (rc==SQLITE_OK) { phase=3; rc=exec(d,"COMMIT"); }
    }
    armed=0;
    if (crash_fault && rc==SQLITE_OK) {
        assert(write(STDOUT_FILENO,"ack\n",4)==4);
        if (!strcmp(mode,"crash-after-ack")) _exit(87);
    }
    if (!fired) assert(rc==SQLITE_OK);
    if (rc>0) assert((rc&255)==SQLITE_IOERR || (rc&255)==SQLITE_FULL);
    assert(rc>=0);
    int64_t autocommit=0; assert(gq_status(d,2,&autocommit)==SQLITE_OK);
    if (!autocommit) assert(exec(d,"ROLLBACK")==SQLITE_OK);
    if (source) assert(gq_close(source)==SQLITE_OK);
    assert(gq_close(d)==SQLITE_OK && gq_close(d)==GQ_HANDLE);
    assert(sqlite3_vfs_register(base,1)==SQLITE_OK && sqlite3_vfs_unregister(&shim)==SQLITE_OK);
    int epoch=verify(dest); if (rc==SQLITE_OK) assert(epoch==1);
    if (!strcmp(scenario,"backup")) assert(verify(src)==1);
    /* Verify recovered state before a fresh checked transaction can change it. */
    assert(gq_open_config(text(dest),0,0,1000000,wal,&d)==SQLITE_OK);
    assert(exec(d,"BEGIN IMMEDIATE")==SQLITE_OK);
    assert(exec(d,"UPDATE t SET epoch=epoch")==SQLITE_OK && exec(d,"COMMIT")==SQLITE_OK);
    assert(gq_close(d)==SQLITE_OK && verify(dest)==epoch);
    printf("{\"skipped\":false,\"events\":%d,\"fired\":%d,\"code\":%lld,\"epoch\":%d,\"fault_phase\":%d}\n",seen,fired,(long long)rc,epoch,first_fault_phase);
    assert(sqlite3_shutdown()==SQLITE_OK && sqlite3_memory_used()==0);
    return 0;
}
