"""P300: generate fight-outcome training data for the fight model.

Parent-policy natural games supply realistic states. At every decision whose
candidates change the deck or relics, each candidate afterstate (plus the
current state) is played against a few fights sampled from the upcoming panel
(p300_teacher.panel), each with a random battle seed and a random entry HP.
One noisy, unbiased label per fight; the model averages the noise away.

Row: features of (state, encounter, entry HP) and the fight result, plus
decision bookkeeping (decision id, candidate index, parent choice) so the
model's decisions can be evaluated against the parent's.
"""
import argparse
import gzip
import json
import random
import time
from pathlib import Path

import p300_common as C
import p300_play as P
import p300_teacher as T

CARD_IDS = len(C.sts.CardId.__members__)
RELIC_IDS = len(C.sts.RelicId.__members__)
ENCOUNTERS = len(C.E.__members__)
POTION_SLOTS = 64
SCALARS = 5
# Layout: cards(2*CARD_IDS) | relics | potions | encounter | scalars
OFF_RELIC = 2 * CARD_IDS
OFF_POTION = OFF_RELIC + RELIC_IDS
OFF_ENCOUNTER = OFF_POTION + POTION_SLOTS
OFF_SCALAR = OFF_ENCOUNTER + ENCOUNTERS
WIDTH = OFF_SCALAR + SCALARS


def state_features(gc):
    """Sparse [index, value] public inventory features (no encounter, no HP)."""
    counts = {}
    for card in gc.deck:
        k = 2 * int(card.id) + (1 if card.upgraded else 0)
        counts[k] = counts.get(k, 0) + 1
    for relic in gc.relics:
        counts[OFF_RELIC + int(relic.id)] = 1
    for potion in gc.potions:
        if potion > 1:  # 0/1 are empty slot markers
            k = OFF_POTION + min(int(potion), POTION_SLOTS - 1)
            counts[k] = counts.get(k, 0) + 1
    counts[OFF_SCALAR + 1] = gc.max_hp / 100
    counts[OFF_SCALAR + 2] = int(gc.act) / 4
    counts[OFF_SCALAR + 3] = int(gc.floor_num) / 57
    counts[OFF_SCALAR + 4] = len(gc.deck) / 40
    return sorted(counts.items())


def fight_features(state, encounter, hp_fraction):
    return state + [(OFF_ENCOUNTER + int(encounter), 1.0), (OFF_SCALAR, hp_fraction)]


def inventory_key(gc):
    return (tuple(T.deck_key(gc)), tuple(sorted(int(r.id) for r in gc.relics)), int(gc.max_hp))


def sample_fights(gc, k, rng):
    fights = T.panel(gc)
    weights = [w for _, w in fights]
    return [fights[i][0] for i in rng.choices(range(len(fights)), weights=weights, k=k)]


TRACE = None  # path of a per-game file naming the fight in progress (crash diagnosis)


def label(gc, encounter, hp_fraction, simulations, seed):
    hp = max(1, round(hp_fraction * gc.max_hp))
    if TRACE:
        TRACE.write_text(json.dumps(dict(encounter=encounter.name, act=int(gc.act), floor=int(gc.floor_num),
                                         screen=int(gc.screen_state), seed=seed, hp=hp)))
    r = C.F.simulate(gc, int(encounter.value), simulations, 3.0, seed, hp)
    return dict(win=bool(r['win']), hp_after=r['hp'] / max(1, r['max_hp']),
                damage=1.0 - r['enemy_hp_end'] / max(1, r['enemy_hp_start']), error=r['error'])


def generate(seed, out_dir, fights_per_state, max_candidates, simulations):
    global TRACE
    TRACE = Path(out_dir) / f'{seed}.trace'
    x, parent = P.runtime()
    sts, A, config = x.R.sts, x.A, x.config
    rng = random.Random(seed * 7919 + 1)
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 20)
    rows, decisions, steps, started = [], 0, 0, time.monotonic()

    def emit_group(states, decision, parent_choice):
        """All candidate states of one decision play the same fights (encounter, HP, seed)."""
        fights = [(e, rng.uniform(0.35, 1.0), rng.getrandbits(62) | 1)
                  for e in sample_fights(states[0][1], fights_per_state, rng)]
        for fight_id, (encounter, hp_fraction, fight_seed) in enumerate(fights):
            for candidate, state_gc in states:
                state = state_features(state_gc)
                result = label(state_gc, encounter, hp_fraction, simulations, fight_seed)
                rows.append(dict(decision=decision, candidate=candidate, parent=parent_choice,
                                 fight=fight_id, encounter=encounter.name, hp=hp_fraction,
                                 features=fight_features(state, encounter.value, hp_fraction), **result))

    while gc.outcome == sts.GameOutcome.UNDECIDED and steps < config['max_steps']:
        steps += 1
        x.R.clock_input(gc, config)
        if gc.screen_state == sts.ScreenState.BATTLE:
            sts.resolve_battle_recorded(gc, config['simulations'], config['boss_multiplier'])
            continue
        actions = list(sts.get_legal_game_actions(gc))
        _, descriptors, _ = A.build_choices(gc)
        chosen = parent.choose(gc, A.obs_vec(gc), actions, descriptors)
        if len(actions) > 1 and int(gc.act) <= 4:
            before = inventory_key(gc)
            afters = []
            for i, action in enumerate(actions):
                copy = C.F.copy_game(gc)
                action.execute(copy)
                if inventory_key(copy) != before:
                    afters.append((i, copy))
            if afters:
                if len(afters) > max_candidates:
                    keep = [a for a in afters if a[0] == chosen]
                    rest = [a for a in afters if a[0] != chosen]
                    afters = keep + rng.sample(rest, max_candidates - len(keep))
                emit_group([(-1, gc)] + afters, decisions, chosen)  # -1: no-change reference
                decisions += 1
        actions[chosen].execute(gc)
    status = x.R.terminal(gc)
    path = Path(out_dir) / f'{seed}.jsonl.gz'
    with gzip.open(path, 'wt') as handle:
        for row in rows:
            handle.write(json.dumps(row) + '\n')
    TRACE.unlink(missing_ok=True)
    return dict(seed=seed, status=status, floor=int(gc.floor_num), rows=len(rows), decisions=decisions,
                seconds=time.monotonic() - started)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('out_dir')
    parser.add_argument('--first-seed', type=int, default=4_000_000_000)
    parser.add_argument('--games', type=int, default=200)
    parser.add_argument('--fights', type=int, default=3)
    parser.add_argument('--max-candidates', type=int, default=4)
    parser.add_argument('--sims', type=int, default=2000)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--one-seed', type=int)
    args = parser.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    seeds = [s for s in range(args.first_seed, args.first_seed + args.games)
             if not (out / f'{s}.jsonl.gz').exists()]
    if args.one_seed is not None:
        print(json.dumps(generate(args.one_seed, out, args.fights, args.max_candidates, args.sims)))
        return
    # One subprocess per game: an engine abort loses only that game.
    import subprocess, sys
    from concurrent.futures import ThreadPoolExecutor

    def isolated(seed):
        cmd = [sys.executable, __file__, str(out), '--one-seed', str(seed), '--fights', str(args.fights),
               '--max-candidates', str(args.max_candidates), '--sims', str(args.sims)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            return json.loads(proc.stdout.strip().splitlines()[-1])
        trace = out / f'{seed}.trace'
        return dict(seed=seed, error=f'exit {proc.returncode}', stderr=proc.stderr[-400:],
                    trace=json.loads(trace.read_text()) if trace.exists() else None)

    with ThreadPoolExecutor(args.workers) as pool, (out / 'games.jsonl').open('a') as log:
        for row in pool.map(isolated, seeds):
            log.write(json.dumps(row) + '\n')
            log.flush()


if __name__ == '__main__':
    main()
