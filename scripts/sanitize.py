#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fresh, bounded generated-path sanitizer run with content-addressed compiler."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
MODULE=importlib.util.spec_from_file_location('control',ROOT/'scripts/sanitize-control.py')
CONTROL=importlib.util.module_from_spec(MODULE);MODULE.loader.exec_module(CONTROL)
TESTS={
    'api':'sqlite public API tests passed',
    'storage':'sqlite storage tests passed',
    'diagnostics':'sqlite statement diagnostics passed',
    'metadata':'sqlite metadata/status tests passed',
    'zeroblob':'sqlite zeroblob public tests passed',
    'files':'sqlite file API tests passed',
    'checkpoint':'sqlite checkpoint public tests passed',
}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot():
    names=['GOOSE_REVISION','sqlite.goose','sqlite.build','CMakeLists.txt','Makefile',
           'scripts/sanitizer-cc.sh','scripts/sanitize.py','scripts/sanitize-control.py',
           'tests/sanitize_fault.goose','tests/sanitize_fault.c']
    names += ['tests/'+name+'.goose' for name in TESTS]
    names += [str(p.relative_to(ROOT)) for p in (ROOT/'native').rglob('*') if p.is_file()]
    return {name:sha(ROOT/name) for name in sorted(set(names))}


def compiler_wrapper(cc,goose):
    wrapper_bytes=(ROOT/'scripts/sanitizer-cc.sh').read_bytes()
    digest=hashlib.sha256(wrapper_bytes+str(cc).encode()+sha(cc).encode()+sha(goose).encode()).hexdigest()
    directory=ROOT/'.build/sanitizer-toolchains'/digest;directory.mkdir(parents=True,exist_ok=True)
    path=directory/'cc'
    if path.exists():
        if path.read_bytes()!=wrapper_bytes:raise RuntimeError('content-addressed wrapper mismatch')
    else:
        with path.open('xb') as stream:stream.write(wrapper_bytes)
        path.chmod(0o755)
    return path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--goose',type=Path,required=True)
    parser.add_argument('--cc',required=True)
    args=parser.parse_args()
    resolved=shutil.which(args.cc)
    if not resolved:parser.error('compiler unavailable')
    cc=Path(resolved).resolve();goose=args.goose.resolve()
    parent=ROOT/'.build/sanitize-runs';parent.mkdir(parents=True,exist_ok=True)
    run=Path(tempfile.mkdtemp(prefix=cc.name+'-',dir=parent))
    environment=dict(os.environ,SANITIZER_CC=str(cc),SANITIZER_COMMAND_LOG=str(run/'compiler-commands.jsonl'),
                     ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',UBSAN_OPTIONS='halt_on_error=1')
    def event(value):
        with (run/'commands.jsonl').open('a') as stream:
            stream.write(json.dumps(value)+'\n');stream.flush();os.fsync(stream.fileno())
    def command(name,cmd,expected=0,env=None):
        event({'event':'started','name':name,'command':[str(v) for v in cmd]})
        with (run/(name+'.stdout')).open('xb') as out,(run/(name+'.stderr')).open('xb') as err:
            child=subprocess.Popen([str(v) for v in cmd],cwd=ROOT,env=env or environment,
                                   stdout=out,stderr=err,start_new_session=True)
            try:code=child.wait(timeout=300)
            except BaseException as error:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                child.wait(timeout=2);event({'event':'failed','name':name,'error':repr(error),'exit':child.returncode});raise
        event({'event':'completed','name':name,'exit':code})
        if expected is not None and code!=expected:raise RuntimeError(f'{name} exit {code}, expected {expected}; see {run}')
        return code,(run/(name+'.stdout')).read_text(errors='replace'),(run/(name+'.stderr')).read_text(errors='replace')
    before=snapshot()
    try:
        version=command('goose-version',[goose,'version'])[1]
        pin=(ROOT/'GOOSE_REVISION').read_text().strip()
        if not pin.startswith(version.split()[1]):raise RuntimeError('compiler pin mismatch')
        wrapper=compiler_wrapper(cc,goose)
        wrapper_bytes=wrapper.read_bytes()
        positives=[]
        for name,marker in TESTS.items():
            binary=run/name
            command('build-'+name,[goose,'build','tests/'+name+'.goose','--cc',wrapper,'--standalone','-o',binary])
            arguments=[binary]
            if name in ('files','checkpoint'):arguments.append(run/(name+'.sqlite'))
            _,out,err=command('test-'+name,arguments)
            lines=out.strip().splitlines()
            accepted={marker}
            if name=='checkpoint':accepted.add(marker+' (WAL unsupported)')
            if len(lines)!=1 or lines[0] not in accepted or err:raise RuntimeError('positive output missing or unexpected: '+name)
            positives.append({'name':name,'output':out.strip(),'binary_sha256':sha(binary)})
        generated=run/'control.c'
        command('emit-control',[goose,'tests/sanitize_fault.goose','--standalone','-o',generated])
        obj=run/'control.o';fixture=run/'fixture.o'
        command('compile-control',[wrapper,'-c',generated,'-o',obj])
        command('compile-fixture',[wrapper,'-c','tests/sanitize_fault.c','-o',fixture])
        symbols=CONTROL.require_instrumentation(obj)
        (run/'generated-symbols.txt').write_text(symbols)
        binary=run/'control'
        command('link-control',[wrapper,obj,fixture,'-lm','-ldl','-lpthread','-o',binary])
        status,output,error=command('control',[binary],expected=None)
        if status==0 or 'AddressSanitizer: heap-buffer-overflow' not in output+error:
            raise RuntimeError('runtime sensitivity control failed')
        # Prove that linking ASan alone is insufficient. Force a real memcpy
        # call in this plain TU; its object must be rejected even though the
        # ASan interceptor diagnoses the memory fault when it is linked.
        plain=run/'control-plain.o'
        command('compile-linkonly',[cc,'-O0','-g','-fno-builtin-memcpy','-c',generated,'-o',plain])
        try:CONTROL.require_instrumentation(plain)
        except RuntimeError:pass
        else:raise RuntimeError('link-only generated object passed the instrumentation gate')
        (run/'linkonly-symbols.txt').write_text(subprocess.check_output(['nm','-u',str(plain)],text=True,timeout=30))
        linkonly=run/'control-linkonly'
        command('link-linkonly',[wrapper,plain,fixture,'-lm','-ldl','-lpthread','-o',linkonly])
        twin_status,twin_out,twin_err=command('linkonly-runtime',[linkonly],expected=None)
        if twin_status==0 or 'AddressSanitizer: heap-buffer-overflow' not in twin_out+twin_err:
            raise RuntimeError('link-only interception counterexample not reproduced')
        if snapshot()!=before or wrapper.read_bytes()!=wrapper_bytes:raise RuntimeError('source drift during sanitizer run')
        record={'schema':2,'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                'sources':before,'goose_sha256':sha(goose),'compiler':str(cc),'compiler_sha256':sha(cc),
                'wrapper_sha256':sha(wrapper),'wrapper':str(wrapper),'cache_scope':'wrapper path includes wrapper/compiler/Goose content digest; pinned toolchain cache key uses32bit path hash, not cryptographic collision resistance',
                'positive_tests':positives,'control':'generated-object ASan+UBSan refs required AND runtime memory error; link-only twin rejected at object gate despite runtime error',
                'generated_sha256':sha(generated),'instrumented_object_sha256':sha(obj),'linkonly_object_sha256':sha(plain),
                'non_pie':True,'native_assertions':'-UNDEBUG appended after Release flags',
                'limits':['System dynamic SQLite is not instrumented','No cold-start TSan classification or engine change','Object instrumentation is not path/branch coverage','No hard memory/disk quota or absence-of-bugs claim']}
        (run/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
        print('Generated sanitizer checks passed: seven public programs, object gate and link-only counterexample; evidence '+str(run))
    except BaseException as error:
        event({'event':'failed','error':repr(error)})
        raise


def terminate(signum,frame):raise SystemExit(128+signum)


if __name__=='__main__':
    signal.signal(signal.SIGTERM,terminate)
    main()
