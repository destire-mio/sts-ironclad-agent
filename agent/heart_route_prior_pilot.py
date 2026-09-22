"""One bounded whole-route intervention on old Ironclad development families.

Only the map heuristic's elite-node value changes. The frozen neural residual,
all other outside decisions and combat budget remain the paired control.
"""
import argparse
from collections import Counter
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import time
import traceback

import heart_early_card_scope as E
import heart_continuous_data as C
import heart_offline_control_evaluation as N


def route_scores(x, gc, actions, descriptors, bonus):
    room = x.R.sts.Room; hp = gc.cur_hp/max(1, gc.max_hp); size = len(gc.deck)
    target_x, target_y, _ = gc.burning_elite

    @lru_cache(None)
    def reachable(col, row):
        if row == target_y: return col == target_x
        return row < target_y and any(reachable(c, row+1) for c in gc.map_node_children(col, row))

    @lru_cache(None)
    def score(col, row):
        if row >= 15: return 0.
        kind = gc.map_node_room(col, row)
        value = {room.REST: 3.5, room.SHOP: 2. if gc.gold >= 150 else -.5,
            room.ELITE: (1.5 if hp > .8 and size >= 14 else -3.5)+bonus,
            room.MONSTER: 1.7 if gc.act == 1 and size < 16 else .5,
            room.EVENT: 1., room.TREASURE: 2.}.get(kind, 0.)
        return value+max((score(c, row+1) for c in gc.map_node_children(col, row)), default=0.)
    values = {}
    for i, (action, descriptor) in enumerate(zip(actions, descriptors)):
        if x.R.kind(descriptor) != x.A.AK_MAP: continue
        col, row = int(action.idx1), gc.cur_map_node_y+1
        values[i] = score(col, row) + (100. if not gc.green_key and target_x >= 0 and reachable(col, row) else 0.)
    return values


def independent_route_scores(x, gc, actions, descriptors, bonus):
    """Bottom-up public-map arithmetic, separate from recursive production."""
    values = {}; health = gc.cur_hp/max(1, gc.max_hp); size = len(gc.deck)
    for row in range(14, -1, -1):
        for col in range(7):
            name = gc.map_node_room(col, row).name
            if name == 'ELITE': value = (1.5 if health > .8 and size >= 14 else -3.5)+bonus
            elif name == 'REST': value = 3.5
            elif name == 'SHOP': value = 2. if gc.gold >= 150 else -.5
            elif name == 'MONSTER': value = 1.7 if gc.act == 1 and size < 16 else .5
            elif name == 'EVENT': value = 1.
            elif name == 'TREASURE': value = 2.
            else: value = 0.
            children = list(gc.map_node_children(col, row))
            values[col, row] = value+max((values.get((c,row+1),0.) for c in children), default=0.)
    result = {}
    for i, (action, d) in enumerate(zip(actions, descriptors)):
        if x.R.kind(d) != x.A.AK_MAP: continue
        key = 100. if not gc.green_key and d[x.A.OFF_BURNING_REACHABLE] else 0.
        result[i] = values.get((int(action.idx1),gc.cur_map_node_y+1),0.)+key
    return result


class RoutePolicy:
    def __init__(self, x, bonus=3.5):
        self.x, self.bonus = x, bonus
        self.base = E.parent_model(x)
        E.require(self.base.model_type == 'first_boss_relic_ranker'
                  and self.base.base.model_type == 'card_context_residual', 'unexpected base policy')

    def choose(self, gc, observation, actions, descriptors):
        x = self.x; parent = self.base.choose(gc, observation, actions, descriptors)
        teacher = x.R.heuristic_choice(gc, actions, descriptors)
        if x.R.kind(descriptors[parent]) != x.A.AK_MAP or x.R.kind(descriptors[teacher]) != x.A.AK_MAP:
            return parent
        scores = route_scores(x, gc, actions, descriptors, self.bonus)
        new_teacher = max(scores, key=scores.get)
        residual = self.base.base.score(x.H.torch.tensor(observation), descriptors)
        result = self.base.base.with_prior(residual, new_teacher)
        # Eligibility guarantees the old winner is a map action. Keep the
        # experiment scoped to map actions, including on newly reached states.
        return max(scores, key=lambda i: float(result[i]))


def independent_choice(policy, gc, observation, actions, descriptors):
    x = policy.x; parent = policy.base.choose(gc, observation, actions, descriptors)
    teacher = x.R.heuristic_choice(gc, actions, descriptors)
    if x.R.kind(descriptors[parent]) != x.A.AK_MAP or x.R.kind(descriptors[teacher]) != x.A.AK_MAP:
        return parent, parent
    scores = independent_route_scores(x, gc, actions, descriptors, policy.bonus)
    new_teacher = max(scores, key=scores.get)
    logits = policy.base.base.score(x.H.torch.tensor(observation), descriptors).tolist()
    logits[new_teacher] += policy.base.base.prior_strength
    return max(scores, key=lambda i: logits[i]), parent


def registered(root):
    reg = E.read(root/'registration.json')
    for path, digest in reg['hashes'].items(): E.require(E.sha(path) == digest, 'bound input changed: '+path)
    plan = E.read(root/'protocol.json')
    E.require(plan['experiment'] == 'E181' and plan['families'] == 64 and plan['elite_bonus'] == 3.5,
              'registered whole-route intervention changed')
    E.require(E.sha(__file__) == reg['runner_sha256'], 'route implementation changed')
    roles = E.read(Path(plan['natural_source'])/'fit-roles.json')
    ordered = sorted(roles,key=lambda seed:(hashlib.sha256((plan['selection_namespace']+str(seed)).encode()).hexdigest(),seed))
    E.require(E.read(root/'families-private.json') == ordered[:64], 'family selection changed')
    learning = Path(plan['learning_evidence']); E.proof(learning/'learning','completion.json')
    E.require(E.read(learning/'learning/report.json')['auxiliary_gate_passed'] is False, 'preceding evidence changed')
    E.proof(Path(plan['behavior_audit']), 'completion.json')
    evidence = E.read(Path(plan['behavior_audit'])/'report.json')
    E.require(evidence['actions']['MAP']['multiple_recorded_actions'] == 0 and
              evidence['native_policy_components']['MAP']['network_changed_heuristic'] == 0,
              'source gap differs')
    return plan


def audit_route(x, run, policy):
    E.require(run['status'] in ('heart_win','death','act3_without_heart') and not run.get('error'),
              'unfinished or faulted route')
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    count = changes = 0; bosses = []; fourth = []; rooms = Counter()
    for step in run['prefix']:
        x.R.clock_input(gc,x.config); E.require(x.R.fingerprint(gc) == step['before'], 'state/RNG mismatch')
        if step['kind'] == 'outside':
            actions = list(x.R.sts.get_legal_game_actions(gc)); _,desc,_ = x.A.build_choices(gc); obs = x.A.obs_vec(gc)
            with x.H.torch.no_grad():
                expected, parent = independent_choice(policy,gc,obs,actions,desc)
                actual = policy.choose(gc,obs,actions,desc)
            E.require(actual == expected and int(actions[actual].bits) == step['action'], 'independent route choice mismatch')
            E.require(x.R.fingerprint(gc) == step['before'], 'scoring changed state/RNG')
            if actual != parent:
                E.require(x.R.kind(desc[actual]) == x.R.kind(desc[parent]) == x.A.AK_MAP, 'non-map intervention')
                changes += 1
            if x.R.kind(desc[actual]) == x.A.AK_MAP:
                target_y = gc.cur_map_node_y+1
                target = x.R.sts.Room.BOSS if target_y >= 15 else gc.map_node_room(int(actions[actual].idx1),target_y)
                rooms[f'{gc.act}:{target.name}'] += 1
            count += 1
        else:
            if gc.act == 3 and gc.cur_room == x.R.sts.Room.BOSS: bosses.append(gc.encounter.name)
            if gc.act == 4:
                E.require(gc.red_key and gc.green_key and gc.blue_key, 'Act4 missing keys')
                fourth.append(gc.encounter.name)
        x.R.replay_step(gc,step,x.config)
    x.R.clock_input(gc,x.config); x.P.verify_terminal(gc,run)
    if run['status'] == 'heart_win':
        E.require(len(set(bosses)) == len(bosses) == 2 and fourth == ['SHIELD_AND_SPEAR','THE_HEART'], 'incomplete Heart route')
    return dict(outside_choices=count, map_interventions=changes, mapped_rooms=dict(rooms),
                terminal_state_rng_verified=True, independent_choice_verified=True)


def evaluate_worker(job,config):
    try:
        root = Path(job['study']); plan = registered(root); x = C.D.runtime(plan['runtime'])
        E.require(E.sha(job['reference']['path']) == job['reference']['sha256'], 'reference changed')
        reference = E.read(job['reference']['path']); policy = RoutePolicy(x, 0. if job['control'] else plan['elite_bonus'])
        E.require(reference['engine_sha256'] == x.identity['engine_sha256'] and
                  reference['checkpoint_sha256'] == x.identity['model_sha256'], 'wrong source identity')
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, job['seed'],20)
        run = x.R.rollout(job['seed'],config,gc=gc,net=policy,record=True,record_samples=False)
        x.R.clock_input(gc,config)
        run.update(terminal_fingerprint=x.R.fingerprint(gc), checkpoint_sha256=E.sha(root/'registration.json'),
            engine_sha256=x.identity['engine_sha256'], search_budget=dict(simulations=8000,boss_multiplier=3,max_replans=256))
        run['audit'] = audit_route(x,run,policy)
        run['first_change'] = N.first_change(x,reference,run)
        if job['control']:
            E.require(run['prefix'] == reference['prefix'] and x.P.terminal_signature(run) == x.P.terminal_signature(reference),
                      'fresh unchanged-parent control differs')
        if job.get('repeat'):
            old = E.read(job['repeat']['path'])
            E.require(E.sha(job['repeat']['path']) == job['repeat']['sha256'] and run['status'] == old['status'] == 'heart_win'
                      and run['prefix'] == old['prefix'] and x.P.terminal_signature(run) == x.P.terminal_signature(old),
                      'fresh winning NN/MCTS replan differs')
            run['fresh_replan_matched'] = True
        result = run
    except Exception: result = dict(status='evaluation_error',seed=job['seed'],error=traceback.format_exc())
    path = Path(job['output']); path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_name(path.name+'.tmp')
    with gzip.open(temporary,'wt',encoding='utf-8') as stream: json.dump(result,stream,separators=(',',':'))
    temporary.replace(path)


def evaluate(root):
    plan = registered(root); E.require(E.read(root/'preflight.json')['status'] == 'passed', 'preflight missing')
    x = C.D.runtime(plan['runtime']); config = dict(x.config,workers=8)
    E.require(config['ascension'] == 20 and config['simulations'] == 8000 and config['boss_multiplier'] == 3, 'combat budget changed')
    refs = E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'),'seed','reference')
    seeds = E.read(root/'families-private.json'); E.require(len(set(seeds)) == len(seeds) == 64, 'assigned denominator changed')
    out = root/'evaluation'; out.mkdir()
    jobs = [dict(mode='prefix',study=str(root),seed=s,reference=refs[s],control=control,
                 output=str(out/('control' if control else 'candidate')/f'{s}.json.gz'))
            for control, assigned in ((True,seeds[:4]),(False,seeds)) for s in assigned]
    deadline = time.monotonic()+plan['timeout_seconds']
    controls = x.H.run_jobs(out,jobs[:4],config,'E181_parent_controls',deadline,worker_fn=evaluate_worker)
    E.require(len(controls) == 4 and all(r['status'] in ('heart_win','death','act3_without_heart') and not r.get('error') for r in controls),
              'control fault; no candidate allocation')
    rows = x.H.run_jobs(out,jobs[4:],config,'E181_whole_route',deadline,worker_fn=evaluate_worker)
    E.require(len(rows) == 64,'assigned games missing')
    faults = [dict(seed=r['seed'],status=r['status'],error=r.get('error')) for r in rows
              if r['status'] not in ('heart_win','death','act3_without_heart') or r.get('error')]
    E.write(out/'faults.json',faults); E.require(not faults,'execution fault, not a death label')
    repeats = [dict(job,repeat=dict(path=job['output'],sha256=E.sha(job['output'])),
                    output=str(out/'repeated'/f'{job["seed"]}.json.gz')) for job,row in zip(jobs[4:],rows) if row['status']=='heart_win']
    reruns = x.H.run_jobs(out,repeats,config,'E181_winner_replans',deadline,worker_fn=evaluate_worker) if repeats else []
    E.require(len(reruns)==len(repeats) and all(r.get('fresh_replan_matched') for r in reruns),'missing winner replan')
    counts = x.B.paired_counts([int(refs[s]['status']=='heart_win') for s in seeds],[int(r['status']=='heart_win') for r in rows])
    report = dict(status='complete',experiment='E181',families=64,counts=counts,
        diagnostic_gate_passed=counts['net_gain'] >= 6 and counts['paired'].get('candidate_only',0) >= 8,
        changed_families=sum(r['first_change']['kind']!='unchanged' for r in rows),
        mapped_interventions=sum(r['audit']['map_interventions'] for r in rows),
        outside_choices=sum(r['audit']['outside_choices'] for r in rows),
        terminal_statuses=dict(Counter(r['status'] for r in rows)),
        new_candidate_games=64,new_control_games=4,winner_replans=len(repeats),
        zero_faults=True,optimizer_updates=0,policy_adoption=False,unseen_acceptance_games=0,
        limits=plan['limits'])
    E.write(out/'report.json',report)
    paths = [Path(j['output']) for j in jobs+repeats]+[out/'report.json',out/'faults.json']
    E.write(out/'completion.json',dict(status='complete',hashes={str(p.relative_to(out)):E.sha(p) for p in paths}))
    print(report,flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',type=Path,required=True)
    evaluate(parser.parse_args().study.resolve())
