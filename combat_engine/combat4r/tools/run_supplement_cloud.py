import pathlib,sys,subprocess,fcntl,json
r=pathlib.Path(__file__).resolve().parents[1];out=r/'evidence/fixed'
# These are the opposite phases of the already-running three workers.
# First-phase processes use disjoint groups; all future processes take the lock.
for mode,worker in [('r',0),('r',2),('q',1)]:
 lock=(out/f'group-{mode}-{worker}-3.lock').open('a')
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:print('owned by primary',mode,worker,flush=True);continue
 fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
 with (r/f'evidence/fixed-supplement-{worker}-{mode}.log').open('a') as f:
  subprocess.run([sys.executable,str(r/'tools/verify_fixed.py'),mode,str(r.parent/'combat4q'),str(worker),'3'],stdout=f,stderr=subprocess.STDOUT,check=True)
 print('group complete',mode,worker,flush=True)
