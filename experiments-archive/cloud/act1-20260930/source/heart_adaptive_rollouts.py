"""A bounded NRPA battle-search diagnostic on the unchanged native simulator.

Policy adaptation is local to one fight/search. It never trains the strategic
policy, changes a game RNG, or carries private battle information across runs.
The sampling-only arm shares the same objective, action support and base bias.
"""
from dataclasses import dataclass
import math
import random
import re
import time


RECIPE = dict(levels=2,alpha=1.,base_end_weight=.1,turn_limit=500,
              action_limit=20000,seconds_per_search=1800.,base_rollouts=8000,
              boss_multiplier=3)
BOSSES = {'SLIME_BOSS','THE_GUARDIAN','HEXAGHOST','AUTOMATON','COLLECTOR',
          'CHAMP','AWAKENED_ONE','TIME_EATER','DONU_AND_DECA','THE_HEART'}


def require(condition, message):
    if not condition: raise ValueError(message)


def probabilities(policy, codes, biases):
    logits = [policy.get(code,0.)+bias for code,bias in zip(codes,biases)]
    maximum = max(logits)
    values = [math.exp(value-maximum) for value in logits]
    total = sum(values)
    require(math.isfinite(total) and total>0, 'invalid search probability')
    return [v/total for v in values]


def adapt(policy, frames, alpha=1.):
    """One sequence-log-probability gradient; every term uses the old policy."""
    updated = dict(policy)
    for codes,biases,chosen in frames:
        probs = probabilities(policy,codes,biases)
        for i,(code,probability) in enumerate(zip(codes,probs)):
            updated[code] = updated.get(code,0.)+alpha*((i==chosen)-probability)
    return updated


def menu(sts, battle, ply):
    actions = list(sts.get_legal_actions(battle))
    require(bool(actions), 'nonterminal battle has no legal actions')
    kinds = [int(a.action_type) for a in actions]
    hand = battle.hand if 0 in kinds else []
    potions = battle.potions if 1 in kinds else []
    codes, biases = [], []
    for action,kind in zip(actions,kinds):
        identity,upgrade = 0,0
        if kind == 0:
            card = hand[action.source_idx]; identity = int(card.id); upgrade = int(card.upgrade_count)
        elif kind == 1:
            i = action.source_idx
            identity = potions[i] if 0<=i<len(potions) else -1
        # Bits distinguish legal targets, selections and duplicate hand slots.
        # Ply retires a selected code: later decisions cannot undo its meaning.
        codes.append((ply,int(action.bits),identity,upgrade))
        biases.append(math.log(RECIPE['base_end_weight']) if kind==4 and 0 in kinds else 0.)
    require(len(codes)==len(set(codes)), 'search action code aliases a legal menu')
    return actions,tuple(codes),tuple(biases)


def score(sts, battle):
    """A shared MC/NRPA objective; intentionally not the original MCTS score.

    Survive first, then remaining HP and potions. Unsuccessful complete plans
    rank by remaining enemy HP fraction; partial/capped paths rank below them.
    This shaping is a search heuristic, never a game-success label.
    """
    outcome = battle.outcome; hp = int(battle.player.cur_hp)
    if outcome == sts.Outcome.UNDECIDED: return (-1.,0.,0.,0.)
    surviving = outcome in (sts.Outcome.PLAYER_VICTORY,sts.Outcome.PLAYER_ESCAPE) and hp>0
    # Native Potion IDs: INVALID=0, EMPTY_POTION_SLOT=1, usable types>=2.
    potion_count = sum(int(p)>1 for p in battle.potions)
    if surviving: return (1.,float(hp),float(potion_count),-float(battle.turn))
    monsters = [m for m in battle.monsters if m.alive or m.half_dead]
    remaining = sum(max(0,int(m.cur_hp)) for m in monsters)
    maximum = sum(max(1,int(m.max_hp)) for m in monsters)
    return (0.,-remaining/max(1,maximum),-float(len(monsters)),-float(battle.turn))


def state_repr(text):
    # BattleContext::sum is an inline static process-wide anti-optimization
    # counter, not part of a battle. Executing any clone increments it.
    result,count=re.subn(r', sum: -?\d+, seed:', ', sum: <process_counter>, seed:',text)
    require(count==1,'unrecognized native battle diagnostic layout')
    return result


def signature(battle):
    return dict(repr=state_repr(repr(battle)),rng=dict(battle.rng_states),outcome=int(battle.outcome),
                turn=int(battle.turn),potions=list(battle.potions),counters=dict(battle.snapshot_counters))


@dataclass
class PathResult:
    value: tuple
    actions: list
    frames: list
    outcome: int
    hp: int
    turn: int


class Search:
    def __init__(self, sts, root, seed, deadline=None, progress=None):
        self.sts=sts; self.root=root; self.rng=random.Random(seed)
        self.deadline=deadline if deadline is not None else time.monotonic()+RECIPE['seconds_per_search']
        self.rollouts=0;self.transitions=0;self.updates=0;self.partial_paths=0
        self.progress=progress

    def rollout(self, policy):
        require(time.monotonic()<self.deadline, 'adaptive search deadline')
        battle=self.root.clone(); actions_taken=[]; frames=[]
        while battle.outcome == self.sts.Outcome.UNDECIDED and battle.turn<RECIPE['turn_limit']:
            require(len(actions_taken)<RECIPE['action_limit'], 'adaptive search action safety limit')
            actions,codes,biases=menu(self.sts,battle,len(actions_taken))
            probs=probabilities(policy,codes,biases); value=self.rng.random(); chosen=len(probs)-1
            for i,p in enumerate(probs):
                value-=p
                if value<0: chosen=i;break
            action=actions[chosen]
            require(action.is_valid(battle), 'native search enumerated an illegal action')
            frames.append((codes,biases,chosen)); actions_taken.append(int(action.bits))
            action.execute(battle);self.transitions+=1
        self.rollouts+=1
        self.partial_paths+=battle.outcome == self.sts.Outcome.UNDECIDED
        if self.progress is not None and self.rollouts%64==0:
            self.progress(dict(rollouts=self.rollouts,transitions=self.transitions,updates=self.updates,
                               partial_paths=self.partial_paths))
        return PathResult(score(self.sts,battle),actions_taken,frames,int(battle.outcome),
                          int(battle.player.cur_hp),int(battle.turn))

    def run(self, budget, adaptive):
        require(type(budget)==int and budget>0, 'invalid rollout budget')
        before=signature(self.root);best=None;outer_policy={}
        # Two balanced nesting levels use exactly the registered rollout budget.
        # Group count is mechanically derived, never selected from outcomes.
        groups=max(1,math.isqrt(budget)) if adaptive else 1
        for group in range(groups):
            child_policy=dict(outer_policy);child_best=None
            count=budget//groups+(group<budget%groups)
            for _ in range(count):
                result=self.rollout(child_policy)
                if child_best is None or result.value>=child_best.value:child_best=result
                if adaptive:
                    child_policy=adapt(child_policy,child_best.frames,RECIPE['alpha']);self.updates+=1
            if best is None or child_best.value>=best.value:best=child_best
            if adaptive:
                outer_policy=adapt(outer_policy,best.frames,RECIPE['alpha']);self.updates+=1
        require(self.rollouts==budget and before==signature(self.root), 'search changed root or rollout budget')
        return best


def verify(sts, root, result):
    """Regenerate every legal menu and execute the witness from an untouched root."""
    before=signature(root);battle=root.clone()
    require(len(result.actions)==len(result.frames),'witness/menu length differs')
    for ply,(bits,frame) in enumerate(zip(result.actions,result.frames)):
        actions,codes,biases=menu(sts,battle,ply);stored_codes,stored_biases,chosen=frame
        require(codes==stored_codes and biases==stored_biases, 'witness legal menu differs')
        require(int(actions[chosen].bits)==bits and actions[chosen].is_valid(battle),'witness chosen action differs')
        actions[chosen].execute(battle)
    require((score(sts,battle),int(battle.outcome),int(battle.player.cur_hp),int(battle.turn))
            ==(result.value,result.outcome,result.hp,result.turn), 'witness terminal differs')
    require(before==signature(root), 'witness replay mutated root')
    return battle
