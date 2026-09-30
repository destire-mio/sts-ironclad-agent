"""Same-RNG Heart research. Recorded prefixes are replayed, never searched again.

Run with the combat4q P300_RUNTIME. All candidate searches run once per root.
Failures are recorded separately and cannot become wins or losses.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import time
import traceback
import importlib.util
import ast
import inspect

os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import p300_common as C

S = C.sts
OUT = Path(os.environ.get('HEART_RESEARCH_OUT', str(C.ROOT / 'runs/heart-research-20260929')))
POTION_NAMES = '''INVALID EMPTY_POTION_SLOT AMBROSIA ANCIENT_POTION ATTACK_POTION BLESSING_OF_THE_FORGE BLOCK_POTION BLOOD_POTION BOTTLED_MIRACLE COLORLESS_POTION CULTIST_POTION CUNNING_POTION DEXTERITY_POTION DISTILLED_CHAOS DUPLICATION_POTION ELIXIR_POTION ENERGY_POTION ENTROPIC_BREW ESSENCE_OF_DARKNESS ESSENCE_OF_STEEL EXPLOSIVE_POTION FAIRY_POTION FEAR_POTION FIRE_POTION FLEX_POTION FOCUS_POTION FRUIT_JUICE GAMBLERS_BREW GHOST_IN_A_JAR HEART_OF_IRON LIQUID_BRONZE LIQUID_MEMORIES POISON_POTION POTION_OF_CAPACITY POWER_POTION REGEN_POTION SKILL_POTION SMOKE_BOMB SNECKO_OIL SPEED_POTION STANCE_POTION STRENGTH_POTION SWIFT_POTION WEAK_POTION'''.split()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


_VERIFIED=False


def verify_runtime():
    global _VERIFIED
    if _VERIFIED:return
    manifest=OUT/'manifest.json'
    if manifest.exists():
        frozen=json.loads(manifest.read_text())
        assert Path(frozen['runtime']).resolve()==C.RUNTIME.resolve(),'wrong research runtime'
        for name,expected in frozen['source_hashes'].items():
            path=Path(name)
            if C.RUNTIME in path.parents or path.name in ('p300_common.py','p300_stage_values.py','p300_teacher.py','guide_rules.py','baixi_rules.py','relic_u.json','p300_play_v12.py','p300_vlate.py','heart_prep_candidate.py') or path.suffix=='.jsonl':
                assert sha(path)==expected,'frozen research dependency changed: '+name
    _VERIFIED=True


def pots(values):
    return [POTION_NAMES[int(p)] for p in values]


def game_info(g):
    return dict(C.summary(g), gold=int(g.gold),
                cards=[dict(id=c.id.name, up=int(c.upgrade_count), type=c.type.name) for c in g.deck],
                relic_names=[r.id.name for r in g.relics], potion_names=pots(g.potions),
                keys=[bool(g.red_key), bool(g.green_key), bool(g.blue_key)])


def combat_info(b):
    p = b.player
    m = b.monsters[0]
    return dict(turn=int(b.turn)+1, hp=int(p.cur_hp), block=int(p.block), energy=int(p.energy),
                strength=int(p.strength), hand=[c.id.name+('+' if c.upgraded else '') for c in b.hand],
                dexterity=int(p.dexterity),artifact=int(p.artifact),
                player_debuffs={k:p.get_status(getattr(S.PlayerStatus,k)) for k in ('WEAK','FRAIL','VULNERABLE')},
                hand_cards=[dict(id=c.id.name,up=bool(c.upgraded),uid=int(c.unique_id),cost=int(c.cost_for_turn),type=c.type.name) for c in b.hand],
                hand_types=[c.type.name for c in b.hand],
                monster_hp=int(m.cur_hp), intent=m.intent, monster_strength=int(m.strength),
                invincible=m.get_status(S.MonsterStatus.INVINCIBLE),
                beat=m.get_status(S.MonsterStatus.BEAT_OF_DEATH),
                powers={k: (int(p.has_status(getattr(S.PlayerStatus,k))) if k in ('CORRUPTION','BARRICADE') else p.get_status(getattr(S.PlayerStatus,k))) for k in
                        ('CORRUPTION','BARRICADE','DEMON_FORM','FEEL_NO_PAIN','DARK_EMBRACE','EVOLVE','INTANGIBLE')},
                potions=pots(b.potions))


def replay_battle(g, row, detailed=False):
    b = S.BattleContext(); b.init(g)
    trace = []
    for j, bits in enumerate(row['actions']):
        a = S.SearchAction.from_bits(bits & 0xffffffff)
        assert a.is_valid(b), ('invalid battle action',j,bits)
        if detailed:
            before = combat_info(b)
            item = dict(index=j,bits=bits,action=a.desc(b),type=a.action_type.name,before=before)
            if a.action_type.name == 'CARD':
                card=b.hand[a.source_idx]
                item.update(card=card.id.name,card_type=card.type.name)
        a.execute(b)
        if detailed:
            item['after']=combat_info(b); trace.append(item)
    assert int(b.outcome)==int(row['outcome']), ('battle outcome',int(b.outcome),row['outcome'])
    b.exit_battle(g)
    return trace


def iter_states(run):
    g=S.GameContext(S.CharacterClass.IRONCLAD, run['seed'],20)
    for step,row in enumerate(run['prefix']):
        C.H.clock_input(g,C.CONFIG)
        yield step,g,row
        if row['kind']=='battle': replay_battle(g,row)
        else:
            a=S.GameAction(row['action'] & 0xffffffff)
            assert a.is_valid(g), ('invalid outside action',step,row)
            a.execute(g)


def root_at(path, step=None, encounter='THE_HEART'):
    verify_runtime()
    run=C.read_run(path)
    for i,g,row in iter_states(run):
        if (step is not None and i==step) or (step is None and row['kind']=='battle' and g.encounter.name==encounter):
            return run,i,C.F.copy_game(g),row
    raise ValueError('root not present')


def profile(path):
    result=dict(path=str(path),sha256=sha(path))
    try:
        run=C.read_run(path); result.update(seed=run['seed'],cohort=Path(path).parent.name,win=run['win'])
        g=S.GameContext(S.CharacterClass.IRONCLAD, run['seed'],20)
        key_events=[]; outside=[]; battles=[]; trace=[]; heart=None
        for step,row in enumerate(run['prefix']):
            C.H.clock_input(g,C.CONFIG)
            keys=[bool(g.red_key),bool(g.green_key),bool(g.blue_key)]
            if row['kind']=='battle':
                entry=game_info(g) if int(g.act)==4 else C.summary(g)
                is_heart=g.encounter.name=='THE_HEART'
                if is_heart:
                    heart=dict(entry,step=step,fingerprint=C.H.fingerprint(g),rng=dict(g.rng_states))
                tt=replay_battle(g,row,is_heart)
                battles.append(dict(entry,hp_after=int(g.cur_hp),step=step))
                if is_heart:trace=tt
            else:
                a=S.GameAction(row['action'] & 0xffffffff)
                assert a.is_valid(g), ('invalid outside',step)
                if int(g.act)>=3:
                    acts=list(S.get_legal_game_actions(g))
                    _,ds,_=C.A.build_choices(g)
                    rec=dict(step=step,screen=g.screen_state.name,act=int(g.act),floor=int(g.floor_num),
                             hp=int(g.cur_hp),max_hp=int(g.max_hp),gold=int(g.gold),action=row['action'],
                             actions=[dict(bits=int(z.bits),idx1=int(z.idx1),idx2=int(z.idx2),
                                           potion=bool(z.is_potion_action),kind=C.H.kind(d)) for z,d in zip(acts,ds)])
                    if g.screen_state.name=='SHOP_ROOM':
                        rec.update(shop_potions=[list(p) for p in g.get_shop_potions()],
                                   shop_cards=[str(c) for c in g.get_shop_cards()],
                                   shop_relics=[list(r) for r in g.get_shop_relics()])
                    outside.append(rec)
                a.execute(g)
            nextkeys=[bool(g.red_key),bool(g.green_key),bool(g.blue_key)]
            if nextkeys!=keys:key_events.append(dict(step=step,act=int(g.act),floor=int(g.floor_num),before=keys,after=nextkeys))
        terminal=dict(status=C.H.terminal(g),act=int(g.act),floor=int(g.floor_num),hp=int(g.cur_hp),max_hp=int(g.max_hp))
        assert all(run[k]==v for k,v in terminal.items()),('terminal mismatch',terminal)
        result.update(status='passed',terminal=terminal,heart=heart,keys=key_events,outside=outside,battles=battles)
        if trace:
            tracepath=OUT/'traces'/f'{Path(path).parent.name}-{run["seed"]}.json.gz'
            tracepath.parent.mkdir(exist_ok=True)
            with gzip.open(tracepath,'wt') as f:json.dump(trace,f)
            result.update(trace=str(tracepath),last=trace[-1],turns=trace[-1]['after']['turn'],
                          player_action_hp_loss=sum(max(0,t['before']['hp']-t['after']['hp']) for t in trace if t['type']!='END_TURN'),
                          enemy_phase_hp_loss=sum(max(0,t['before']['hp']-t['after']['hp']) for t in trace if t['type']=='END_TURN'),
                          cap_actions=sum(t.get('card_type')=='ATTACK' and t['before']['invincible']==0 for t in trace),
                          dead_potions=trace[-1]['after']['potions'])
    except Exception:result.update(status='fault',error=traceback.format_exc())
    return result


def search_job(job):
    path,variant,budget,mult=job
    r=dict(path=str(path),variant=variant,budget=budget,boss_multiplier=mult)
    try:
        run,step,g,row=root_at(path)
        r.update(seed=run['seed'],recorded_win=run['win'],root=C.H.fingerprint(g),rng=dict(g.rng_states))
        fn=getattr(C.F,'resolve_'+('combat4' if variant=='rollout4' else 'combat3' if variant=='rollout3' else 'combat4q'))
        started=time.monotonic();cpu=time.process_time()
        res=fn(g,budget,mult)
        assert C.H.terminal(g) in ('heart_win', 'death'), 'nonterminal Heart search'
        r.update(seconds=time.monotonic()-started,cpu_seconds=time.process_time()-cpu)
        r.update({k:res[k] for k in res if k!='actions'})
        r.update(actions=[int(a) for a in res['actions']],status='complete',win=C.H.terminal(g)=='heart_win',hp=int(g.cur_hp),
                 final_rng=dict(g.rng_states),final_fingerprint=C.H.fingerprint(g),
                 action_match=list(res['actions'])==row['actions'])
    except Exception:r.update(status='fault',error=traceback.format_exc())
    return r


_BASE=None
_CHOOSERS={}


def baseline():
    global _BASE
    if _BASE is None:
        path=Path(os.environ.get('HEART_BASELINE_FILE',str(OUT/'baseline/p300_play_v12.py')))
        spec=importlib.util.spec_from_file_location('heart_v12_frozen',path)
        _BASE=importlib.util.module_from_spec(spec);spec.loader.exec_module(_BASE)
        # Extend metadata counters only; the frozen choice functions remain unchanged.
        _BASE.FIX3_RULES=(*_BASE.FIX3_RULES,'heart_research')
    return _BASE


def outside_choice(P,arm,x,parent,g,actions,ds):
    if arm not in _CHOOSERS:
        tree=ast.parse(inspect.getsource(P.play));loop=next(n for n in ast.walk(tree) if isinstance(n,ast.While))
        start=next(i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='chosen' for t in n.targets))
        end=next(i for i,n in enumerate(loop.body) if isinstance(n,ast.If) and ast.unparse(n.test)=='prefix is not None')
        head=ast.parse('''
def choose(x,parent,gc,actions,descriptors):
    A,sts=x.A,x.R.sts
    features=set(ARM.split('+'))
    overrides=teacher_calls=teacher_changed=guides=fixes=simulations_used=0
    elite_thr=flame_thr=route_params=None
    branch=explore=0
    strength_cache,route_cache,guide2_cache={},{},{}
    fix3=dict.fromkeys(FIX3_RULES,0)
    fix3_log=[]
''').body[0]
        head.body+=loop.body[start:end]+[ast.Return(value=ast.Name(id='chosen',ctx=ast.Load()))]
        scope=dict(vars(P),ARM=P.rollout_arm(set(arm.split('+'))))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[head],type_ignores=[])),'<heart-outside-audit>','exec'),scope)
        _CHOOSERS[arm]=scope['choose']
    return _CHOOSERS[arm](x,parent,g,actions,ds)


def prep_scan(path):
    """Select first disagreement per run/rule, before consulting terminal outcomes."""
    import heart_prep_candidate as Q
    P=baseline();x,parent=P.runtime()
    run=C.read_run(path);found={};audited=0;changed=0
    for step,g,row in iter_states(run):
        if row['kind']=='battle' or g.act<3 or g.floor_num<45:continue
        if g.screen_state.name not in ('REST_ROOM','SHOP_ROOM','REWARDS'):continue
        actions=list(S.get_legal_game_actions(g));_,ds,_=x.A.build_choices(g)
        chosen=outside_choice(P,run['arm'],x,parent,g,actions,ds)
        audited+=1;changed+=int(actions[chosen].bits)!=row['action']
        for rule in ('rest90','rest100','potionfirst','lateengine'):
            if rule in found:continue
            better=Q.choose(rule,x,g,actions,ds,chosen)
            if better!=chosen:
                found[rule]=dict(path=str(path),seed=run['seed'],rule=rule,step=step,base_action=int(actions[chosen].bits),
                                 candidate_action=int(actions[better].bits),state=game_info(g),screen=g.screen_state.name)
    return dict(status='complete',seed=run['seed'],roots=list(found.values()),audited=audited,changed=changed)


def prep_job(job):
    import heart_prep_candidate as Q
    root,variant=job
    r=dict(seed=root['seed'],path=root['path'],step=root['step'],rule=root['rule'],variant=variant)
    P=baseline();original=P.loss_fixes3
    try:
        run,step,g,_=root_at(root['path'],root['step'])
        r.update(root=C.H.fingerprint(g),rng=dict(g.rng_states),state=game_info(g))
        x,parent=P.runtime();actions=list(S.get_legal_game_actions(g));_,ds,_=x.A.build_choices(g)
        local_choice=outside_choice(P,run['arm'],x,parent,g,actions,ds)
        assert int(actions[local_choice].bits)==root['base_action'],'baseline outside action differs across platforms'
        r['baseline_choice_verified']=True
        chosen=root['base_action'] if variant=='base' else root['candidate_action']
        a=S.GameAction(chosen & 0xffffffff);assert a.is_valid(g);a.execute(g)
        changes=[]
        if variant!='base':
            def override(x,g,acts,ds,chosen,parent):
                prev=original(x,g,acts,ds,chosen,parent)
                chosen=prev[0] if prev is not None else chosen
                better=Q.choose(root['rule'],x,g,acts,ds,chosen)
                if better!=chosen:
                    changes.append(dict(act=int(g.act),floor=int(g.floor_num),before=int(acts[chosen].bits),after=int(acts[better].bits)))
                    return better,'heart_research'
                return prev
            P.loss_fixes3=override
        arm=P.rollout_arm(set(run['arm'].split('+')))+'+traj'
        record_dir=OUT/'prep-traces'/root['rule']/variant
        started=time.monotonic();cpu=time.process_time()
        result=P.play(run['seed'],arm,[101,102,103,104],500,start=g,record_dir=record_dir)
        assert result['status'] in ('heart_win', 'death'), 'nonterminal preparation suffix: '+result['status']
        r.update(result,variant=variant,rule=root['rule'],status='fault' if result['error'] else 'complete',
                 terminal=result['status'],seconds=time.monotonic()-started,cpu_seconds=time.process_time()-cpu,
                 extra_changes=changes,action=chosen,suffix_trace=str(record_dir/f'{run["seed"]}-{arm}.json.gz'))
    except Exception:r.update(status='fault',error=traceback.format_exc())
    finally:P.loss_fixes3=original
    return r


def spear_job(job):
    root, variant = job
    r = dict(seed=root['seed'], path=root['path'], step=root['step'],
             rule='spear160', variant=variant, split=root['split'], stratum=root['stratum'])
    P = baseline()
    original = C.F.resolve_combat4q
    try:
        run, _, g, _ = root_at(root['path'], root['step'])
        assert g.encounter.name == 'SHIELD_AND_SPEAR' and g.screen_state.name == 'BATTLE'
        r.update(root=C.H.fingerprint(g), rng=dict(g.rng_states), state=game_info(g))
        fights = []
        def resolve(gc, budget, multiplier):
            entry = C.summary(gc)
            if variant == 'candidate' and gc.encounter.name == 'SHIELD_AND_SPEAR':
                budget = 160000
            cpu = time.process_time()
            result = original(gc, budget, multiplier)
            fights.append(dict(entry, budget=budget, boss_multiplier=multiplier,
                               hp_after=int(gc.cur_hp), cpu_seconds=time.process_time()-cpu,
                               simulations=int(result['simulations'])))
            return result
        C.F.resolve_combat4q = resolve
        arm = P.rollout_arm(set(run['arm'].split('+'))) + '+traj'
        record_dir = OUT/'spear-traces'/variant
        started = time.monotonic(); cpu = time.process_time()
        result = P.play(run['seed'], arm, [101, 102, 103, 104], 500, start=g, record_dir=record_dir)
        assert result['status'] in ('heart_win', 'death'), 'nonterminal Spear suffix: '+result['status']
        r.update(result, variant=variant, rule='spear160',
                 status='fault' if result['error'] else 'complete', terminal=result['status'],
                 seconds=time.monotonic()-started, cpu_seconds=time.process_time()-cpu,
                 combat_costs=fights, suffix_trace=str(record_dir/f'{run["seed"]}-{arm}.json.gz'))
    except Exception:
        r.update(status='fault', error=traceback.format_exc())
    finally:
        C.F.resolve_combat4q = original
    return r


def audit_job(row):
    if 'natural_trace' in row:
        result = profile(row['natural_trace'])
        return dict(seed=result.get('seed'),variant='natural-replay',
                    path=row['natural_trace'],status=result['status'],error=result.get('error'))
    r=dict(seed=row['seed'],variant=row['variant'],rule=row.get('rule','search'))
    try:
        _,_,g,_=root_at(row['path'],row.get('step'))
        assert C.H.fingerprint(g)==row['root'] and dict(g.rng_states)==row['rng']
        if row.get('rule') == 'rest90' and row['variant'] == 'candidate':
            # Check the delivered rule against every tested campfire root.
            sources = [C.ROOT/'agent/p300_play.py', OUT/'delivery/p300_play_v14.py']
            defs = [next(n for n in ast.parse(path.read_text()).body
                         if isinstance(n, ast.FunctionDef) and n.name == 'heart_rest90') for path in sources]
            assert ast.dump(defs[0]) == ast.dump(defs[1]), 'local/cloud campfire rule differs'
            scope = {}
            exec(compile(ast.Module(body=[defs[0]], type_ignores=[]), '<delivered-rest90>', 'exec'), scope)
            root = next(r for r in json.loads((OUT/'prep-jobs.json').read_text())
                        if r['seed'] == row['seed'] and r['rule'] == 'rest90')
            actions = list(S.get_legal_game_actions(g)); _, descriptors, _ = C.A.build_choices(g)
            chosen = next(i for i, action in enumerate(actions) if int(action.bits) == root['base_action'])
            x, _ = baseline().runtime()
            actual = scope['heart_rest90'](x, g, actions, descriptors, chosen)
            assert int(actions[actual].bits) == row['action'], 'delivered campfire action differs'
            r['delivery_rule_match'] = True
        if 'suffix_trace' in row:
            if 'action' in row:
                a=S.GameAction(row['action'] & 0xffffffff);assert a.is_valid(g);a.execute(g)
            suffix=C.read_run(row['suffix_trace'])
            for item in suffix['prefix']:
                C.H.clock_input(g,C.CONFIG)
                if item['kind']=='battle':replay_battle(g,item)
                else:
                    a=S.GameAction(item['action'] & 0xffffffff);assert a.is_valid(g);a.execute(g)
            assert C.H.terminal(g)==row['terminal'] and int(g.cur_hp)==row['hp']
            assert int(g.act)==row['act'] and int(g.floor_num)==row['floor']
        else:
            detail=row['seed'] in (3900012803, 3900012594) and row['variant'] in ('base','boss6')
            trace=replay_battle(g,row,detail)
            if detail:
                label = 'rescue' if row['seed'] == 3900012803 else 'loss'
                tracepath=OUT/f'budget-{label}-{row["seed"]}-{row["variant"]}.json.gz'
                with gzip.open(tracepath,'wt') as handle:json.dump(trace,handle)
            assert C.H.fingerprint(g)==row['final_fingerprint']
            assert dict(g.rng_states)==row['final_rng']
        assert C.H.terminal(g) in ('heart_win', 'death'), 'nonterminal audited result'
        assert (C.H.terminal(g) == 'heart_win') == row['win'], 'win label differs from replay'
        r.update(status='passed',final_fingerprint=C.H.fingerprint(g))
    except Exception:r.update(status='fault',error=traceback.format_exc())
    return r


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['profile','search','prep-scan','prep','spear','audit']);p.add_argument('--workers',type=int,default=8)
    p.add_argument('--limit',type=int);p.add_argument('--output',required=True);p.add_argument('--paths');p.add_argument('--variants',default='base:80000:12,h160:160000:12,h320:320000:12,boss6:80000:6,rollout3:80000:12')
    a=p.parse_args();assert 1<=a.workers<=8
    paths=json.loads(Path(a.paths).read_text()) if a.paths else [str(p) for p in sorted((OUT/'traj').glob('*/*.gz'))]
    if a.limit:paths=paths[:a.limit]
    if a.mode=='profile':jobs=paths;fn=profile
    elif a.mode=='prep-scan':jobs=paths;fn=prep_scan
    elif a.mode=='prep':jobs=[(root,v) for root in paths for v in ('base','candidate')];fn=prep_job
    elif a.mode=='spear':jobs=[(root,v) for root in paths for v in ('base','candidate')];fn=spear_job
    elif a.mode=='audit':jobs=paths;fn=audit_job
    else:jobs=[(path,v.split(':')[0],int(v.split(':')[1]),float(v.split(':')[2])) for path in paths for v in a.variants.split(',')];fn=search_job
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    assert not out.exists(),'new output required; avoid accidental repeated search'
    with ProcessPoolExecutor(a.workers) as pool,out.open('w') as f:
        for n,fut in enumerate(as_completed([pool.submit(fn,j) for j in jobs]),1):
            row=fut.result();f.write(json.dumps(row)+'\n');f.flush()
            if row['status']=='fault' or n%25==0 or len(jobs)<10:print(json.dumps(dict(done=n,total=len(jobs),seed=row.get('seed'),variant=row.get('variant'),status=row['status'],error=row.get('error'),seconds=row.get('seconds'))),flush=True)


if __name__=='__main__':main()
