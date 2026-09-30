import pathlib,subprocess,sys,os,concurrent.futures
root=pathlib.Path(__file__).resolve().parents[1];parent=pathlib.Path(sys.argv[1]).resolve();workers=int(sys.argv[2]);assert 1<=workers<=8
os.environ['OMP_NUM_THREADS']=os.environ['OPENBLAS_NUM_THREADS']='1'
def run(i):
 for mode in (['q','r'] if i%2==0 else ['r','q']):
  with (root/f"evidence/{os.environ.get('COMBAT4R_RESULT_SET','fixed')}-{i}-{mode}.log").open('a') as log:
   subprocess.run([sys.executable,str(root/'tools/verify_fixed.py'),mode,str(parent),str(i),str(workers)],stdout=log,stderr=subprocess.STDOUT,check=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(run,range(workers)))
