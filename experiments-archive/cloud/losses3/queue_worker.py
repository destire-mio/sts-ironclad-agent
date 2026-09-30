"""Four independent OS processes, no Python coordinator; atomic job claims."""
import os
os.environ['PYTHONDONTWRITEBYTECODE']='1'
import sys,json,time,traceback
from pathlib import Path
from death_metadata import one as metadata_one
from probes import one as probe_one
OUT=Path.home()/'sts/runs/losses3'
wid=sys.argv[1];q=OUT/'queue';results=OUT/'queue-results';claims=OUT/'queue-claims'
results.mkdir(exist_ok=True);claims.mkdir(exist_ok=True)
with (OUT/f'queue-worker-{wid}.jsonl').open('a') as log:
    while True:
        found=False
        for path in sorted(q.glob('*.json')):
            if path.name.startswith('.'):continue  # macOS archive sidecars are not jobs
            target=results/path.name;claim=claims/path.name
            if target.exists():continue
            try:fd=os.open(claim,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            except FileExistsError:continue
            os.write(fd,json.dumps({'worker':wid,'pid':os.getpid(),'time':time.time()}).encode());os.close(fd)
            job=json.loads(path.read_text());found=True;start=time.time()
            try:
                r=probe_one(job['job']) if job['type']=='probe' else metadata_one((job['cohort'],job['row']))
            except BaseException:r={'error':traceback.format_exc()}
            r.update(queue_job=path.name,queue_type=job['type'],worker=wid,wall_seconds=time.time()-start)
            temp=results/(path.name+'.tmp');temp.write_text(json.dumps(r));temp.replace(target)
            log.write(json.dumps({'job':path.name,'error':r.get('error'),'mismatch':r.get('mismatch',r.get('control_mismatch')),'seconds':r['wall_seconds']})+'\n');log.flush()
            break
        if not found:
            if (OUT/'queue-closed').exists():break
            time.sleep(2)
