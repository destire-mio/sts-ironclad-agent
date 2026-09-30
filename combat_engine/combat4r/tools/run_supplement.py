import pathlib,subprocess,sys,concurrent.futures
r=pathlib.Path(__file__).resolve().parents[1];parent=pathlib.Path(sys.argv[1]).resolve();indices=list(map(int,sys.argv[2:]));assert len(indices)<=4
def run(i):
 mode='r' if i%2==0 else 'q'
 with (r/f'evidence/fixed-supplement-{i}-{mode}.log').open('a') as log:
  subprocess.run([sys.executable,str(r/'tools/verify_fixed.py'),mode,str(parent),str(i),'4'],stdout=log,stderr=subprocess.STDOUT,check=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=len(indices)) as p:list(p.map(run,indices))
