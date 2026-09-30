"""Freeze real reachable roots before collecting or inspecting candidate outcomes."""
import collections
import hashlib
import json
import os
from pathlib import Path
import shutil

os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')
import p300_common as C

STUDY = C.ROOT / 'runs/combat-valuenet-20260927'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def split(seed):
    bucket = int(hashlib.sha256(f'combat-value-v1:{seed}'.encode()).hexdigest()[:8], 16) % 100
    return 'train' if bucket < 60 else 'valid' if bucket < 75 else 'test'


def main():
    assert not (STUDY / 'roots.json').exists(), 'root manifest is immutable'
    paths = set()
    for name in ('d1-boss.jsonl', 'd4-heart-values.jsonl', 'd5-act2boss.jsonl', 'd5-act3boss1.jsonl'):
        for row in map(json.loads, (C.ROOT / 'runs/p300-fight-decomposition' / name).read_text().splitlines()):
            paths.add(row['path'])
    candidates = collections.defaultdict(list)
    imports = []
    for number, path in enumerate(sorted(paths)):
        digest = sha(path)
        run = C.read_run(path)
        family = int(run['seed'])
        local = STUDY / 'episodes' / f'{digest}.json.gz'
        local.parent.mkdir(parents=True, exist_ok=True)
        if not local.exists():
            shutil.copyfile(path, local)
        assert sha(local) == digest == sha(path)
        imports.append(dict(source=path, snapshot=str(local), sha256=digest, family=family))
        act3_number = 0
        for index, game in C.battle_states(run):
            state = C.summary(game)
            if not C.is_boss(game) or state['act'] < 2:
                continue
            if state['act'] == 3:
                if state['floor'] < 50:
                    continue
                act3_number += 1
            stage = 'heart' if state['encounter'] == 'THE_HEART' else f'act{state["act"]}boss'
            if stage not in ('heart', 'act2boss', 'act3boss'):
                continue
            fingerprint = C.H.fingerprint(game)
            assert fingerprint == run['prefix'][index]['before'], (path, index, 'replay fingerprint differs')
            row = dict(family=family, split=split(family), path=str(local), source=path,
                       sha256=digest, index=index, stage=stage, boss_number=act3_number if stage=='act3boss' else 1,
                       state=state, fingerprint=fingerprint)
            row['id'] = hashlib.sha256(f'{digest}:{index}'.encode()).hexdigest()[:20]
            candidates[family, stage, row['boss_number']].append(row)
        if (number + 1) % 25 == 0:
            print(dict(episodes=number+1, groups=len(candidates)), flush=True)
    # One trajectory per family/slot, hash order independent of outcomes.
    roots = [min(rows, key=lambda r:r['id']) for rows in candidates.values()]
    roots.sort(key=lambda r:(r['split'],r['stage'],r['id']))
    roles = {s:sorted({r['family'] for r in roots if r['split']==s}) for s in ('train','valid','test')}
    assert all(not set(roles[a]) & set(roles[b]) for a,b in (('train','valid'),('train','test'),('valid','test')))
    protocol = dict(schema='combat-value-study-v1', roots_sha256=None,
        split='SHA256(combat-value-v1:original_game_seed) first uint32 mod100: train<60, valid<75, test>=75',
        family='Original natural game seed; all behavior repeats, checkpoints, branches and RNG variants grouped.',
        pool='All naturally reached Act2/Act3/Heart bosses in trajectories referenced by frozen D1/D4/D5; one hash-selected entry per family/stage/boss slot. No new seeds or synthetic deck/HP edits.',
        labels=dict(trajectories=12,samples=8,teacher_sims=256,search_seed=927,
            definition='Best exact terminal witness from 256 simulations; binary win and win*remaining_HP/maxHP. Half sampled paths are teacher best, half original heuristic random rollouts; snapshots from first half of path.',
            noise='Finite-budget search can miss wins; state features omit RNG and some rule details; correlated branches; historical parent reachability distribution. Not optimal value nor whole-game win labels.'),
        model=dict(width=512,hidden=32,outputs=['win_probability','expected_hp_fraction'],
                   epochs=40,batch=256,adamw_lr=.002,weight_decay=.0001,seed=927,selection='minimum family-weighted validation BCE+0.5*MSE; test untouched'),
        designs=[dict(round=1,mode='prior',strength=2.,decay_visits=32,
                      behavior='Add 2*(V-.5)/sqrt(1+n/32) to UCT; V=.8*pwin+.2*expectedHP. Terminal rollouts and executable witnesses unchanged.'),
                 dict(round=2,mode='rollout',guided_steps=2,probability=.5,
                      behavior='Original rollout except first two actions: 50% greedy one-step value lookahead; exact terminal outcomes only. Same frozen model; no test-driven parameter scan.')],
        single_fight=dict(reference='reuse, same freshly built core; simulation calibration 32000*12 per replan',
            timing='Per-entry baseline calibration then both arms run same total wall cap and per-round cap (calibration total/rounds); serial interleaving, alternating order. Deadline finishes current atomic batch of16 then executes terminal witness; failures remain faults.',
            repeats=2,confidence='Paired seed-family cluster bootstrap, 20000 resamples, percentile 95% CI; same family indices for all arms.',
            gate='Complete zero-fault paired test; combined win difference>=.03 and 95% CI lower>0; each stage point difference>=0; overall HP difference>=0; candidate median time ratio<=1.03 and p95<=1.10. Both prespecified candidates evaluated; gate adjusted with 97.5% CI for selection between two.',
            max_designs=2),
        full_game=dict(condition='single-fight gate only',first_seed=5000000000,games_per_arm=512,
                       baseline='sims32+boss12+rest+reuse+svsel+svcard',candidate='sims32+boss12+rest+valuenet+svsel+svcard'),
        resources=dict(workers=1,maximum_without_low_load=3,torch_threads=1),
        evidence=['synthetic_checks','single_fight_development','single_fight_family_holdout','full_game_development','fresh_full_game_confirmation'],
        roles=roles,counts=dict(collections.Counter((r['split']+':'+r['stage']) for r in roots)))
    (STUDY/'roots.json').write_text(json.dumps(roots,indent=2)+'\n')
    protocol['roots_sha256']=sha(STUDY/'roots.json')
    (STUDY/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    (STUDY/'episode-imports.json').write_text(json.dumps(imports,indent=2)+'\n')
    print(protocol['counts'],flush=True)


if __name__=='__main__':
    main()
