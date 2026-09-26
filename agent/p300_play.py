"""P300: play natural A20 games with the parent outside network, optionally
letting the simulation teacher (p300_teacher) take deck-changing decisions.

Arms:
  parent  - parent network for every outside decision (control)
  teacher - card rewards and card-select screens (smith, removal, transform)
            decided by simulated-fight deck scores; everything else parent.
Stage-wise results (per boss/act) are recorded for high-power comparisons.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import time
from pathlib import Path

import p300_common as C
import p300_teacher as T
import heart_early_card_scope as ES

_X = _PARENT = None
_MODEL = None


def fight_model():
    """Fight model named by P300_FIGHT_MODEL, loaded once per worker."""
    global _MODEL
    if _MODEL is None:
        import os
        import torch
        import p300_fight_model as FM
        torch.set_num_threads(1)
        blob = torch.load(os.environ['P300_FIGHT_MODEL'], weights_only=False, map_location='cpu')
        _MODEL = FM.FightModel()
        _MODEL.load_state_dict(blob['state'])
        _MODEL.eval()
    return _MODEL


_HV = None


def heart_values():
    """Causal Heart value table (D4): add / up / rm effects on Heart win probability."""
    global _HV
    if _HV is None:
        _HV = json.loads((C.ROOT / 'runs/p300-fight-decomposition/heart-value-table.json').read_text())
    return _HV


def hv_choice(gc, actions, indices, skip_threshold):
    """Pick by the Heart value table; None when a candidate's effect is not classifiable."""
    hv = heart_values()
    before = T.deck_key(gc)
    scores = {}
    for i in indices:
        copy = C.F.copy_game(gc)
        actions[i].execute(copy)
        added, removed = T.deck_delta(before, T.deck_key(copy))
        base = lambda n: n.rstrip('+')
        if not added and not removed:
            scores[i] = skip_threshold                      # skip / no change
        elif len(added) == 1 and not removed:
            scores[i] = hv['add'].get(base(added[0]), 0.0)   # take a card
        elif len(added) == 1 and len(removed) == 1 and added[0] == removed[0] + '+':
            scores[i] = hv['up'].get(removed[0], 0.0)        # upgrade
        elif len(removed) == 1 and not added:
            scores[i] = hv['rm'].get(base(removed[0]), 0.0)  # remove
        else:
            return None                                      # transform etc.: defer to parent
    return max(indices, key=lambda i: scores[i])


def model_scores(gc, actions, indices):
    """Panel value predicted by the fight model for each candidate afterstate (full HP)."""
    import numpy as np
    import torch
    import p300_fight_data as FD
    fights = T.panel(gc)
    total_w = sum(w for _, w in fights)
    rows, owners = [], []
    for i in indices:
        copy = C.F.copy_game(gc)
        actions[i].execute(copy)
        state = FD.state_features(copy)
        for encounter, w in fights:
            rows.append(FD.fight_features(state, encounter.value, 1.0))
            owners.append((i, w))
    x = np.zeros((len(rows), FD.WIDTH), dtype=np.float32)
    for r, feats in enumerate(rows):
        for k, v in feats:
            x[r, k] = v
    with torch.no_grad():
        values = fight_model().value(torch.from_numpy(x)).numpy()
    scores = {i: 0.0 for i in indices}
    for (i, w), v in zip(owners, values):
        scores[i] += w * float(v) / total_w
    return scores


def runtime():
    global _X, _PARENT
    if _X is None:
        _X = ES.load_runtime(C.RUNTIME)
        _PARENT = ES.parent_model(_X)
    return _X, _PARENT


def teacher_indices(x, gc, actions, descriptors, parent_choice):
    """Candidate indices the teacher decides among, or None to defer to parent."""
    A, sts = x.A, x.R.sts
    kinds = [x.R.kind(d) for d in descriptors]
    if gc.screen_state == sts.ScreenState.REWARDS and A.AK_REWARD_CARD in kinds:
        # Parent orders reward collection; teacher only decides the card pick itself.
        if kinds[parent_choice] not in (A.AK_REWARD_CARD, A.AK_REWARD_SKIP):
            return None
        return [i for i, k in enumerate(kinds) if k in (A.AK_REWARD_CARD, A.AK_REWARD_SKIP)]
    if gc.screen_state == sts.ScreenState.CARD_SELECT:
        picks = [i for i, k in enumerate(kinds) if k == A.AK_CARD_SELECT]
        return picks if len(picks) > 1 else None
    return None


def pre_boss_rest(x, gc, actions, descriptors):
    """Index of REST at the campfire right before a boss when HP is low, else None.

    Never overrides the Act 3 campfire while the ruby key (Recall) is still missing.
    """
    sts = x.R.sts
    if gc.screen_state != sts.ScreenState.REST_ROOM:
        return None
    last_row = int(gc.cur_map_node_y) == 14 or int(gc.act) == 4
    if not last_row or gc.cur_hp >= 0.75 * gc.max_hp:
        return None
    if int(gc.act) == 3 and not gc.red_key:
        return None
    for i, action in enumerate(actions):
        if x.R.kind(descriptors[i]) == x.A.AK_REST and action.idx1 == 0:
            return i
    return None


def play(seed, arm, seeds, simulations, record_dir=None):
    x, parent = runtime()
    sts, A, config = x.R.sts, x.A, x.config
    features = set(arm.split('+'))
    boss_multiplier = 12.0 if 'boss12' in features else config['boss_multiplier']
    boss_multiplier = next((float(f[4:]) for f in features if f.startswith('boss') and f[4:].isdigit()), boss_multiplier)
    # simsN: base search budget N thousand per decision (production 8).
    base_sims = next((int(f[4:]) * 1000 for f in features if f.startswith('sims') and f[4:].isdigit()), config['simulations'])
    # adaptN: extend searches without a surviving plan up to N x base; hpNN: boss HP target.
    adapt = next((float(f[5:]) for f in features if f.startswith('adapt')), None)
    hp_target = next((int(f[2:]) / 100 for f in features if f.startswith('hp') and f[2:].isdigit()), 0.0)
    simulations_used = 0
    overrides = 0
    record = [] if record_dir else None
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 20)
    started = time.monotonic()
    bosses, teacher_calls, teacher_changed, steps = [], 0, 0, 0
    error = None
    try:
        while gc.outcome == sts.GameOutcome.UNDECIDED and steps < config['max_steps']:
            steps += 1
            x.R.clock_input(gc, config)
            if gc.screen_state == sts.ScreenState.BATTLE:
                entry = C.summary(gc)
                boss = C.is_boss(gc)
                if 'fast' in features:
                    result = C.F.resolve_fast(gc, base_sims, boss_multiplier, 16)
                elif adapt is not None:
                    result = C.F.resolve_adaptive(gc, base_sims, boss_multiplier, adapt, hp_target)
                else:
                    result = sts.resolve_battle_recorded(gc, base_sims, boss_multiplier)
                simulations_used += result['simulations']
                if boss:
                    bosses.append(dict(entry, won=gc.outcome != sts.GameOutcome.PLAYER_LOSS, hp_after=int(gc.cur_hp)))
                continue
            actions = list(sts.get_legal_game_actions(gc))
            _, descriptors, _ = A.build_choices(gc)
            chosen = parent.choose(gc, A.obs_vec(gc), actions, descriptors)
            if 'rest' in features:
                rest = pre_boss_rest(x, gc, actions, descriptors)
                if rest is not None:
                    overrides += rest != chosen
                    chosen = rest
            if len(actions) > 1 and ({'hvsel', 'hvcard', 'hvcard2'} & features):
                indices = teacher_indices(x, gc, actions, descriptors, chosen)
                on_select = gc.screen_state == sts.ScreenState.CARD_SELECT and 'hvsel' in features
                on_card = (gc.screen_state == sts.ScreenState.REWARDS and
                           ('hvcard' in features or ('hvcard2' in features and int(gc.act) >= 2)))
                if indices and (on_select or on_card):
                    best = hv_choice(gc, actions, indices, 0.02)
                    if best is not None:
                        teacher_calls += 1
                        teacher_changed += best != chosen
                        chosen = best
            late_only = 'late' in features and int(gc.act) < 3
            if 'model' in features and len(actions) > 1 and not late_only:
                indices = teacher_indices(x, gc, actions, descriptors, chosen)
                if indices:
                    scores = model_scores(gc, actions, indices)
                    best = max(indices, key=lambda i: scores[i])
                    # gateN: keep the parent's pick unless the model prefers another by > N/1000.
                    gate = next((int(f[4:]) / 1000 for f in features if f.startswith('gate')), None)
                    if gate is not None and chosen in scores and scores[best] - scores[chosen] <= gate:
                        best = chosen
                    teacher_calls += 1
                    teacher_changed += best != chosen
                    chosen = best
            if 'teacher' in features and len(actions) > 1:
                indices = teacher_indices(x, gc, actions, descriptors, chosen)
                if indices:
                    detail = {} if record is not None else None
                    scores = T.score_candidates(gc, actions, indices, seeds, simulations, detail)
                    best = max(indices, key=lambda i: scores[i])
                    if record is not None:
                        record.append(dict(floor=int(gc.floor_num), act=int(gc.act), screen=int(gc.screen_state),
                                           hp=int(gc.cur_hp), max_hp=int(gc.max_hp), parent=chosen, teacher=best,
                                           observation=x.R.sparse(A.obs_vec(gc)),
                                           descriptors=[x.R.sparse(d) for d in descriptors],
                                           actions=[int(a.bits) for a in actions], **detail))
                    teacher_calls += 1
                    teacher_changed += best != chosen
                    chosen = best
            actions[chosen].execute(gc)
        status = x.R.terminal(gc)
    except Exception as exc:
        status, error = 'execution_error', f'{type(exc).__name__}: {exc}'
    row = dict(seed=seed, arm=arm, status=status, win=status == 'heart_win', act=int(gc.act),
                floor=int(gc.floor_num), bosses=bosses, teacher_calls=teacher_calls,
                teacher_changed=teacher_changed, rest_overrides=overrides, simulations=simulations_used, error=error, seconds=time.monotonic() - started)
    if record_dir:
        import gzip
        path = Path(record_dir) / f'{seed}-{arm}.json.gz'
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, 'wt') as handle:
            json.dump(dict(row, decisions=record), handle)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    parser.add_argument('--arms', default='parent,teacher')
    parser.add_argument('--first-seed', type=int, default=3_000_000_000)
    parser.add_argument('--games', type=int, default=64)
    parser.add_argument('--teacher-seeds', type=int, default=4)
    parser.add_argument('--teacher-sims', type=int, default=500)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--record-dir')
    args = parser.parse_args()
    # Fresh seed block, far outside the historical 32-bit seed ranges used before.
    seeds = [args.first_seed + i for i in range(args.games)]
    teacher_seeds = list(range(101, 101 + args.teacher_seeds))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            row = json.loads(line)
            done.add((row['seed'], row['arm']))
    jobs = [(s, a) for s in seeds for a in args.arms.split(',') if (s, a) not in done]
    with ProcessPoolExecutor(args.workers) as pool, out.open('a') as handle:
        futures = [pool.submit(play, s, a, teacher_seeds, args.teacher_sims, args.record_dir) for s, a in jobs]
        for future in as_completed(futures):
            handle.write(json.dumps(future.result()) + '\n')
            handle.flush()


if __name__ == '__main__':
    main()
