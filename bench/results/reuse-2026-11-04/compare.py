# SPDX-License-Identifier: Apache-2.0
# Captured sampling loop: expects baseline-bin/reuse-bin beside this file.
# It pins CPU2. Coordinate a timing window before manually replaying it.
import json,time,subprocess,resource,statistics,os
from pathlib import Path
root=Path(__file__).parent
os.sched_setaffinity(0,{2})
samples=[]
for mode,size,n in [('text',32,1000000),('text',4096,500000),('text',65536,100000),('blob',1048576,10000)]:
 for name in ['baseline','reuse']:
  subprocess.run([str(root/(name+'-bin')),'100',mode,str(size)],check=True,capture_output=True)
 for i in range(7):
  for name in (['baseline','reuse'] if i%2==0 else ['reuse','baseline']):
   before=resource.getrusage(resource.RUSAGE_CHILDREN); start=time.perf_counter_ns()
   r=subprocess.run([str(root/(name+'-bin')),str(n),mode,str(size)],capture_output=True,text=True,check=True)
   wall=time.perf_counter_ns()-start;after=resource.getrusage(resource.RUSAGE_CHILDREN)
   assert r.stdout.strip()==str(n*size)
   samples.append(dict(name=name,mode=mode,size=size,n=n,run=i,wall_ns=wall,cpu_ns=round((after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)*1e9)))
 for name in ['baseline','reuse']:
  relevant=[s for s in samples if s['name']==name and s['mode']==mode and s['size']==size]
  print(mode,size,name,'median wall',statistics.median(s['wall_ns'] for s in relevant),'median cpu',statistics.median(s['cpu_ns'] for s in relevant),flush=True)
(root/'compare.json').write_text(json.dumps(samples,indent=2)+'\n')
