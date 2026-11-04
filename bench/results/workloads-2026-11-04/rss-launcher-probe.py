# SPDX-License-Identifier: Apache-2.0
import hashlib,json,os,pathlib,resource,subprocess,sys,tempfile
padding=bytearray(64*1024*1024)
for i in range(0,len(padding),4096):padding[i]=1
with tempfile.TemporaryFile() as stdout,tempfile.TemporaryFile() as stderr:
 p=subprocess.Popen(['/usr/bin/true'],stdout=stdout,stderr=stderr)
 pid,status,usage=os.wait4(p.pid,0);p.returncode=os.waitstatus_to_exitcode(status);assert p.returncode==0
 direct=usage.ru_maxrss
with tempfile.TemporaryDirectory() as tmp:
 out=pathlib.Path(tmp)/'rss'
 subprocess.run(['/usr/bin/time','-o',str(out),'-f','%M','--','/usr/bin/true'],check=True)
 native=int(out.read_text().strip())
assert native<len(padding)//2048
print(json.dumps({'scope':'Linux launch-path check, not a SQLite benchmark. Direct child peak can include pre-exec Python RSS; GNU time launches the target from its small native image. Approximate accounting and native pre-exec floor remain.', 'allocated_parent_bytes':len(padding),'parent_peak_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'direct_wait4_child_peak_kib':direct,'gnu_time_target_peak_kib':native,'python_version':sys.version,'gnu_time_version':subprocess.check_output(['/usr/bin/time','--version'],text=True).splitlines()[0],'binary_sha256':{pathlib.Path(p).name:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in (sys.executable,'/usr/bin/time','/usr/bin/true')},'probe_source_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()},indent=2))
