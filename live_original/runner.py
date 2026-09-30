"""Original-authoritative combat4/P300 runner; no reload or candidate reruns."""
from __future__ import annotations
import argparse, ast, copy, hashlib, json, os, sys, time, traceback
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
OLD = BASE / 'sts-rl-agent-live-original'
RUNTIME = HERE / 'runtime'
ARM = 'sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4'
sys.dont_write_bytecode = True
os.environ.update(PYTHONDONTWRITEBYTECODE='1', P300_RUNTIME=str(RUNTIME),
    STS_LIGHTSPEED_BUILD=str(RUNTIME / 'engine'), ALIGNMENT_COMPACT_RECORDS='1',
    OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
sys.path[:0] = [str(OLD), str(RUNTIME / 'p300/agent')]
from steam import live_run as L
from steam.live_policy import LivePolicy as BasePolicy
from steam.live_search import LiveSearch as BaseSearch
from sim_patch.parity.core import write_json, sha256
DRIVER_SOURCE = Path(__file__).read_text()
DRIVER_SHA256 = hashlib.sha256(DRIVER_SOURCE.encode()).hexdigest()
BASE_TRANSPORT = L.transport

def transport(view, policy):
    g=view['game']
    if g['screen_type']=='EVENT':
        event=g['screen_state'].get('event_id');fields=view['live_run']['event_fields']
        if event=='FaceTrader' and fields.get('screen')=='INTRO':return 'choose 0'
        if event=='Winding Halls' and fields.get('screenNum')==0:return 'choose 0'
    return BASE_TRANSPORT(view,policy)


def load_selector():
    """Extract the unchanged outside body from the frozen production play()."""
    import p300_play as P
    source = RUNTIME / 'p300/agent/p300_play.py'
    tree = ast.parse(source.read_text())
    play = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'play')
    attempt = next(n for n in play.body if isinstance(n, ast.Try))
    loop = next(n for n in attempt.body if isinstance(n, ast.While))
    start = next(i for i,n in enumerate(loop.body) if isinstance(n, ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='actions' for t in n.targets))
    finish = next(i for i,n in enumerate(loop.body) if isinstance(n, ast.Expr)
        and ast.unparse(n)=='actions[chosen].execute(gc)')
    # All setup and every production rule retain their original order.
    fn = copy.deepcopy(play); fn.name = 'select_live'
    fn.body = copy.deepcopy(play.body[:play.body.index(attempt)])
    fn.body += ast.parse('x.R.clock_input(gc, config)').body
    fn.body += copy.deepcopy(loop.body[start:finish])
    fn.body += ast.parse('return actions, descriptors, chosen').body
    module=ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))
    exec(compile(module,str(source),'exec'),P.__dict__)
    return P, ast.unparse(module)


class Policy(BasePolicy):
    def __init__(self, search, seed):
        super().__init__(search, seed)
        self.P, self.selector_source = load_selector()
        self.x, self.parent = self.P.runtime()
        self.sync_count = 0
        global ACTIVE_POLICY
        ACTIVE_POLICY = self

    def sync(self, view):
        if (view['game']['screen_type']=='EVENT' and
                view['game']['screen_state'].get('event_id')=='Match and Keep!'):
            raise ValueError('Match and Keep board and revealed-card memory cannot be imported')
        super().sync(view)
        g=view['game']
        if g['screen_type']=='EVENT' and g['screen_state'].get('event_id')=='WeMeetAgain':
            fields=view['live_run']['event_fields'];options=g['screen_state']['options']
            # Java uses zero for an absent gold offer; native uses -1. An
            # unavailable potion must also clear the preceding event's slot.
            info=dict(gold=-1 if options[1]['disabled'] else fields['goldAmount'],
                potion_index=fields['potionOption']['slot'] if 'potionOption' in fields else -1)
            self.native.sync_run(self.gc,dict(info=info))
        self.sync_count += 1

    def choose(self, view):
        self.sync(view)
        actions, descriptors, chosen = self.P.select_live(self.gc.seed, ARM, [], 0, start=self.gc)
        action=actions[chosen]
        commands=self.commands(action,view)
        if self.gc.screen_state==self.sts.ScreenState.SHOP_ROOM and not action.is_potion_action:
            group={'CARD':'cards','RELIC':'relics','POTION':'potions'}.get(action.rewards_action_type.name)
            if group:self.shop_purchase=(group,int(action.idx1))
        return action,commands,dict(chosen=chosen,rule='production_p300_play_body',
            actions=[int(a.bits) for a in actions],commands=commands)


class Search(BaseSearch):
    def next_action(self, view):
        self.selection_view=view
        return super().next_action(view)

    def _selection_uuid(self, pile, index):
        uid=getattr(self.battle,pile)[index].unique_id
        if uid not in self.mapper.uuids.values():
            # Exhausting Armaments under Corruption can generate a Dead Branch
            # card immediately before its picker opens. No PLAYER_NORMAL boundary
            # occurred to register the new UUID. Require every ordered pile to
            # match before applying the existing identity mapper at this boundary.
            combat=self.selection_view['game']['combat_state']
            exact=True
            for name in ('hand','draw_pile','discard_pile','exhaust_pile'):
                original=combat[name];native=getattr(self.battle,name)
                if len(original)!=len(native) or any(
                    self.comparator.original_card(o)!=self.comparator.simulator_card(s)
                    for o,s in zip(original,native)):
                    exact=False;break
            if exact:
                self.mapper.refresh(self.battle,self.selection_view)
                self.selection_identity_refreshes=getattr(self,'selection_identity_refreshes',0)+1
        return super()._selection_uuid(pile,index)

    def confirmation(self, view):
        if super().confirmation(view):return True
        # A duplicated Armaments can put native execution in the next picker
        # while Java still needs confirmation of the previous, full picker.
        # Acknowledge only the selection already made by the saved search plan.
        g=view['game'];available=view['available_commands'];state=g['screen_state']
        return (self.battle is not None and self.pending_multi is None and
            self.battle.input_state==self.sts.InputState.CARD_SELECT and
            g['screen_type']=='HAND_SELECT' and 'confirm' in available and
            'choose' not in available and bool(state.get('selected')) and
            len(state['selected'])==state.get('max_cards'))


class Original(L.Original):
    def call(self, op, **arguments):
        translation=None
        if op in ('live_reload','live_rng_restore','fixture','controlled_run_fixture'):
            raise RuntimeError('natural evaluation forbids state reset: '+op)
        if op=='live_checkpoint':
            raise RuntimeError('checkpoints disabled; no replay for combat outcome selection')
        if op=='command' and not arguments.get('command','').startswith('start'):
            previous=getattr(self,'last_view',{}).get('game',{})
            arguments.setdefault('play_time_seconds',previous.get('floor',0)*45)
            if arguments.get('command')=='bowl':
                choices=previous.get('choice_list',[])
                if previous.get('screen_type')!='CARD_REWARD' or 'bowl' not in choices:
                    raise ValueError('Singing Bowl is not offered by the original')
                translation=dict(requested='bowl',executed='choose '+str(choices.index('bowl')))
                arguments['command']=translation['executed']
        result=super().call(op,**arguments)
        # Probe already appends every response to rpc.jsonl.gz, and the driver
        # persists each complete before/after step. Avoid a third whole-run
        # in-memory copy, which caused swap and a large serialization peak.
        self.rpc.clear()
        if translation:result['live_command_translation']=translation
        self.last_view=result
        return result


def run(seed, out):
    L.LivePolicy=Policy; L.LiveSearch=Search; L.Original=Original; L.transport=transport
    args=SimpleNamespace(runtime=RUNTIME,oracle=BASE/'ironclad-alignment/oracle',out=out,
        seed=seed,simulations=40000,max_decisions=6000,stop_on_divergence=False,
        replay_prefix=None,reload_on_hp_shortfall=0,max_reloads_per_battle=0)
    error=None
    try:
        L.run(args)
    except BaseException as exc:
        error=repr(exc)
        traceback.print_exc()
    if not (out/'result.json').exists():
        out.mkdir(parents=True,exist_ok=True)
        write_json(out/'result.json',dict(seed=seed,status='fault',error=error))
    result=json.loads((out/'result.json').read_text())
    result.update(arm=ARM,driver_sha256=DRIVER_SHA256,no_reload=True)
    (out/'driver-source.py').write_text(DRIVER_SOURCE)
    if 'ACTIVE_POLICY' in globals():
        result.update(outside_state_imports=ACTIVE_POLICY.sync_count,
            combat_state_imports=ACTIVE_POLICY.search.plans,
            synchronization_count=ACTIVE_POLICY.sync_count+ACTIVE_POLICY.search.plans,
            selection_identity_refreshes=getattr(ACTIVE_POLICY.search,'selection_identity_refreshes',0))
    write_json(out/'result.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('divergences','battles','traceback')},ensure_ascii=False),flush=True)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seed',type=int,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();result=run(args.seed,args.out.resolve())
    raise SystemExit(0 if result.get('completed_natural_runs') else 2)
