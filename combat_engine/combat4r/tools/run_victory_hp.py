import pathlib,subprocess,sys,concurrent.futures,os
r=pathlib.Path(__file__).resolve().parents[1];workers=int(sys.argv[1]);assert 1<=workers<= (8 if sys.platform=='darwin' else 4)
os.environ['OMP_NUM_THREADS']=os.environ['OPENBLAS_NUM_THREADS']=os.environ['MKL_NUM_THREADS']='1'
def run(args):
 dataset,i=args
 with (r/f'evidence/victory-hp/{dataset}-{i}.log').open('a') as f:subprocess.run([sys.executable,str(r/'tools/verify_victory_hp.py'),str(i),dataset],stdout=f,stderr=subprocess.STDOUT,check=True)
for dataset in ['fixed','feed-fixed']:
 with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(run,[(dataset,i) for i in range(workers if dataset=='fixed' else min(2,workers))]))
