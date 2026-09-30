import os,sys,pathlib,subprocess
r=pathlib.Path(__file__).resolve().parents[1]
os.environ.update(COMBAT4R_INPUT_SET='feed-inputs',COMBAT4R_RESULT_SET='feed-fixed',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
for mode in ['q','r']:
 with (r/f'evidence/feed-final-{mode}.log').open('w') as f:subprocess.run([sys.executable,str(r/'tools/verify_feed.py'),mode,str(r.parent/'combat4q'),'0','1'],stdout=f,stderr=subprocess.STDOUT,check=True)
