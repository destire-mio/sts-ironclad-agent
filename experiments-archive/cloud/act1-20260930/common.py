import os,sys,json,gzip,hashlib
from pathlib import Path
O=Path(__file__).resolve().parent
ROOT=Path.home()/'sts'
os.environ.update(PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',P300_RUNTIME=str(ROOT/'combat4r/runtime-delivery'))
sys.path.insert(0,str(O/'source'))
import p300_common as C
C.ROOT=ROOT/'principles'
import p300_stage_values as SV
SV.RUNS=ROOT/'principles/runs/p300-fight-decomposition'
import p300_heart_values as HV
if hasattr(HV,'RUNS'): HV.RUNS=SV.RUNS
import p300_play_v21 as P
import snap as E
S=C.sts
TR=ROOT/'runs/traj-c42'
def raw(seed):return json.load(gzip.open(next(TR.glob(f'{seed}-*.json.gz')),'rt'))
def step(g,z):
 C.H.clock_input(g,C.CONFIG)
 if z['kind']=='battle':
  b=S.BattleContext();b.init(g)
  for bit in z['actions']:
   a=S.SearchAction.from_bits(bit&0xffffffff)
   assert a.is_valid(b),'illegal battle';a.execute(b)
  assert int(b.outcome)==z['outcome'],'outcome mismatch';b.exit_battle(g)
 else:
  a=S.GameAction(z['action']&0xffffffff);assert a.is_valid(g),'illegal outside';a.execute(g)
def restore(seed,index):
 r=raw(seed);g=S.GameContext(S.CharacterClass.IRONCLAD,seed,20)
 for z in r['prefix'][:index]:step(g,z)
 C.H.clock_input(g,C.CONFIG)
 return g,r
