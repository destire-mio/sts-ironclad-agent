import os
os.environ['PYTHONDONTWRITEBYTECODE']='1'
import json,gzip,sys,collections
from pathlib import Path
OUT=Path.home()/'sts/runs/losses3'
sys.path.insert(0,str(OUT/'source'))
import p300_common as C
import extract_v3 as E
S=C.sts
def restore(raw,stop):
    g=S.GameContext(S.CharacterClass.IRONCLAD,raw['seed'],20)
    for step in raw['prefix'][:stop]:
        C.H.clock_input(g,C.CONFIG)
        if step['kind']=='battle':
            b=S.BattleContext();b.init(g)
            for bits in step['actions']:
                a=S.SearchAction.from_bits(bits&0xffffffff);assert a.is_valid(b);a.execute(b)
            assert int(b.outcome)==step['outcome'];b.exit_battle(g)
        else:
            a=S.GameAction(step['action']&0xffffffff);assert a.is_valid(g);a.execute(g)
    C.H.clock_input(g,C.CONFIG)
    return g
def run():
    out=[]
    for f in sorted((OUT/'replayed').glob('*.json.gz')):
        r=json.load(gzip.open(f,'rt'));raw=None
        for s in r['steps']:
            b=s['before'];a=s.get('chosen',{})
            if a.get('kind')=='EVENT' and a.get('item')=='Falling':
                if raw is None:raw=json.load(gzip.open(next((OUT/'raw').glob(f"{r['seed']}-*.json.gz")),'rt'))
                g=restore(raw,s['index']);acts=list(S.get_legal_game_actions(g));opts=[]
                for act in acts:
                    if act.is_potion_action:continue
                    trial=C.F.copy_game(g);before=collections.Counter(E.card(c) for c in trial.deck);act.execute(trial);after=collections.Counter(E.card(c) for c in trial.deck)
                    opts.append({'bits':int(act.bits),'idx':int(act.idx1),'removed':list((before-after).elements()),'hp_after':int(trial.cur_hp)})
                out.append({'seed':r['seed'],'index':s['index'],'floor':b['floor'],'kind':'falling','chosen':a,'removed':s['removed'],'options':opts})
            if a.get('kind')=='EVENT' and a.get('item')=='Vampires' and s['added']:
                out.append({'seed':r['seed'],'index':s['index'],'floor':b['floor'],'kind':'vampires','before':b,'after':s['after'],'removed':s['removed'],'added':s['added']})
    (OUT/'event-audit.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
if __name__=='__main__':run()
