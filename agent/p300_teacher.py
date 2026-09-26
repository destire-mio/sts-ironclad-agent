"""P300 simulation teacher: score deck-changing choices by simulated upcoming fights.

For each candidate action, the action is applied to a copy of the game and the
resulting deck/relics are played against a panel of upcoming elites and bosses
with the production combat search. All candidates share the same battle seeds
(common random numbers), so the comparison is far less noisy than whole-game
terminal outcomes. HP is set to max for panel fights: this measures deck
strength, not current health.
"""
import p300_common as C

E = C.E
ELITES = {1: [E.GREMLIN_NOB, E.LAGAVULIN, E.THREE_SENTRIES],
          2: [E.GREMLIN_LEADER, E.SLAVERS, E.BOOK_OF_STABBING],
          3: [E.GIANT_HEAD, E.NEMESIS, E.REPTOMANCER]}
BOSSES = {1: [E.HEXAGHOST, E.SLIME_BOSS, E.THE_GUARDIAN],
          2: [E.AUTOMATON, E.COLLECTOR, E.CHAMP],
          3: [E.AWAKENED_ONE, E.TIME_EATER, E.DONU_AND_DECA]}

CROSS_ACT_UNSAFE = {E.COLLECTOR, E.AUTOMATON, E.GREMLIN_LEADER, E.REPTOMANCER}


def panel(gc):
    """[(encounter, weight)] of fights that matter for the rest of the run."""
    act = int(gc.act)
    fights = []
    if act <= 3:
        fights += [(e, 1.0) for e in ELITES[act]]
        fights.append((gc.boss, 3.0))
    if act <= 2:
        fights += [(e, 0.5) for e in ELITES[act + 1] if e not in CROSS_ACT_UNSAFE]
        # Summoning bosses (Collector, Automaton) abort the engine (INVALID
        # summon) when spawned outside their own act; skip them across acts.
        fights += [(e, 1.0) for e in BOSSES[act + 1] if e not in CROSS_ACT_UNSAFE]
    if act >= 2:
        fights.append((E.SHIELD_AND_SPEAR, 1.0))
    # The Heart always counts: early decks are scored on how much of it they chew through.
    fights.append((E.THE_HEART, 3.0 if act >= 3 else 1.5 if act == 2 else 1.0))
    return fights


def fight_value(result):
    """Win: 1 + remaining HP fraction. Loss: fraction of enemy HP removed (<1)."""
    if result['win']:
        return 1.0 + result['hp'] / max(1, result['max_hp'])
    start = max(1, result['enemy_hp_start'])
    return max(0.0, min(0.99, 1.0 - result['enemy_hp_end'] / start))


def fight_values(gc, seeds, simulations, fights):
    """Per-fight mean value over seeds, in panel order."""
    values = []
    for encounter, _ in fights:
        rs = [C.F.simulate(gc, int(encounter.value), simulations, 3.0, seed, int(gc.max_hp)) for seed in seeds]
        values.append(sum(fight_value(r) for r in rs) / len(rs))
    return values


def weighted(values, fights):
    return sum(v * w for v, (_, w) in zip(values, fights)) / sum(w for _, w in fights)


def deck_score(gc, seeds, simulations, fights=None):
    fights = fights or panel(gc)
    return weighted(fight_values(gc, seeds, simulations, fights), fights)


def deck_key(gc):
    return sorted(f'{c.id.name}{"+" if c.upgraded else ""}' for c in gc.deck)


def deck_delta(before, after):
    """(added, removed) card names between two sorted deck lists."""
    from collections import Counter
    b, a = Counter(before), Counter(after)
    return sorted((a - b).elements()), sorted((b - a).elements())


def score_candidates(gc, actions, indices, seeds, simulations, detail=None):
    """Apply each candidate to a copy and score the resulting state; returns {index: score}.

    If `detail` is a dict it is filled with the panel, per-candidate fight values and deck deltas.
    """
    fights = panel(gc)
    before = deck_key(gc)
    scores = {}
    for i in indices:
        copy = C.F.copy_game(gc)
        actions[i].execute(copy)
        values = fight_values(copy, seeds, simulations, fights)
        scores[i] = weighted(values, fights)
        if detail is not None:
            added, removed = deck_delta(before, deck_key(copy))
            detail.setdefault('candidates', {})[i] = dict(values=values, score=scores[i],
                                                          added=added, removed=removed)
    if detail is not None:
        detail['panel'] = [(e.name, w) for e, w in fights]
    return scores
