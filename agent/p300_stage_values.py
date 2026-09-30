"""P300: combine per-stage causal value tables into one deck-change score.

P(win) = prod_s p_s over the remaining stages s, so for a deck change c
    d log P(win) ~= sum_s  delta_s(c) / p_s
where delta_s(c) is the measured change of stage-s survival when c is applied
to real stage-entry decks (p300_heart_values.py) and p_s the measured base
survival. Elite stages also count the HP they leave for the next boss:
    + HP_WEIGHT * delta_hp_after_s(c)
Keys: 'add:CARD', 'up:CARD', 'rm:CARD'. Unknown keys score 0.
"""
import collections
import hashlib
import json
from pathlib import Path

RUNS = Path(__file__).resolve().parent.parent / 'data' / 'p300-fight-decomposition'
LEGACY_SEEDS = 4  # Historical D4-D6 files predate per-row battle_seeds.
# d log P(next boss) / d(HP fraction), from the hp75/hp50 rows of the boss tables (~0.3).
HP_WEIGHT = 0.3

SOURCES = {
    'heart': ('d4-heart-values.jsonl', None),
    'act2boss': ('d5-act2boss.jsonl', None),
    # Mind Bloom's optional act-1 boss fights also sit in act 3: keep floor >= 50 only.
    'act3boss': ('d5-act3boss1.jsonl', lambda r: r['state']['floor'] >= 50),
    'elite1': ('d6-elite1.jsonl', None),
    'elite2': ('d6-elite2.jsonl', None),
    'elite3': ('d6-elite3.jsonl', None),
    'shield_spear': ('d6-shield_spear.jsonl', None),
    'act1boss': ('d7-act1boss.jsonl', None),
    'act1hall': ('d7-act1hall.jsonl', None),
    # Natural entry HP versions (the full-HP act-1 tables show ~no risk: base 97-100%).
    'act1hall_n': ('d8-act1hall-natural.jsonl', None),
    'elite1_n': ('d8-elite1-natural.jsonl', None),
    'act1boss_n': ('d8-act1boss-natural.jsonl', None),
}
# Stages whose HP cost also matters for the next boss (elites and ordinary fights).
ELITE_STAGES = {'elite1', 'elite2', 'elite3', 'shield_spear', 'act1hall', 'act1hall_n', 'elite1_n'}
# Stages still ahead when deciding in a given act. The act-3 table stands in for
# both act-3 bosses (the second one was not measured separately).
REMAINING = {
    1: ['elite1', 'act2boss', 'elite2', 'act3boss', 'act3boss', 'elite3', 'shield_spear', 'heart'],
    2: ['elite2', 'act2boss', 'elite3', 'act3boss', 'act3boss', 'shield_spear', 'heart'],
    3: ['elite3', 'act3boss', 'act3boss', 'shield_spear', 'heart'],
    4: ['shield_spear', 'heart'],
}


def load_stage(path, keep):
    with open(path) as handle:
        rows = [json.loads(line) for line in handle]
    metadata = Path(str(path) + '.manifest.json')
    if metadata.exists():
        manifest = json.loads(metadata.read_text())
        identity = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        assigned = {(r['path'], r['index']) for r in manifest['states']}
        observed = {(r['path'], r['index']) for r in rows}
        if (len(rows) != len(assigned) or observed != assigned or
                any(r.get('collection_id') != identity or r.get('battle_seeds') != manifest['battle_seeds']
                    for r in rows)):
            raise ValueError('incomplete stage collection or rows differing from manifest')
    for r in rows:
        if r.get('status', 'complete') != 'complete':
            raise ValueError('incomplete or faulted stage sample')
    rows = [r for r in rows if keep is None or keep(r)]
    if not rows:
        return None
    trials = [len(r['battle_seeds']) if 'battle_seeds' in r else LEGACY_SEEDS for r in rows]
    if any(n <= 0 or any(not 0 <= v <= n for v in r['results'].values())
           for r, n in zip(rows, trials)):
        raise ValueError('invalid stage trial count or win count')
    base = sum(r['results']['base'] / n for r, n in zip(rows, trials)) / len(rows)
    win, hp = collections.defaultdict(list), collections.defaultdict(list)
    for r, n in zip(rows, trials):
        b = r['results']['base']
        hb = r.get('hp_after', {}).get('base')
        for key, v in r['results'].items():
            if ':' not in key:
                continue
            win[key].append((v - b) / n)
            if hb is not None and key in r['hp_after']:
                hp[key].append(r['hp_after'][key] - hb)
    mean = lambda xs: sum(xs) / len(xs)
    return dict(base=base, decks=len(rows), win={k: mean(v) for k, v in win.items()},
                hp={k: mean(v) for k, v in hp.items()})


def build():
    stages = {}
    for name, (file, keep) in SOURCES.items():
        path = RUNS / file
        if path.exists() and path.stat().st_size:
            table = load_stage(path, keep)
            if table:
                stages[name] = table
    return stages


_TABLES = None


def tables():
    global _TABLES
    if _TABLES is None:
        _TABLES = build()
    return _TABLES


# Optional act-1 near-term stages (feature 'sva1'): about four ordinary fights remain
# after floor 5 and each counts once, plus the act-1 boss.
ACT1_STAGES = ['act1hall', 'act1hall', 'act1hall', 'act1hall', 'act1boss']


def act1_stages(act1):
    """act1: False/0 off, True/1 default (four ordinary fights), 2 = eight ordinary fights."""
    if not act1:
        return []
    if act1 == 'natural':
        return ['act1hall_n'] * 4 + ['elite1_n', 'act1boss_n']
    return ['act1hall'] * (4 * int(act1)) + ['act1boss']


def score(key, act, act1=False):
    """Approximate d log P(win) of a deck change key ('add:X', 'up:X', 'rm:X') decided in `act`."""
    total = 0.0
    stages = REMAINING[min(max(act, 1), 4)]
    if act1 and act <= 1:
        stages = act1_stages(act1) + stages
    for stage in stages:
        t = tables().get(stage)
        if t is None:
            continue
        total += t['win'].get(key, 0.0) / max(0.05, t['base'])
        if stage in ELITE_STAGES:
            total += HP_WEIGHT * t['hp'].get(key, 0.0)
    return total


if __name__ == '__main__':
    t = tables()
    print({k: (round(v['base'], 3), v['decks']) for k, v in t.items()})
    for act in (1, 2, 3):
        adds = sorted(((score(k, act), k) for k in t['heart']['win'] if k.startswith('add:')), reverse=True)
        print(act, 'top', [(k, round(s, 3)) for s, k in adds[:8]])
        print(act, 'bottom', [(k, round(s, 3)) for s, k in adds[-5:]])
