"""Independent public deck decoder for the fixed printed-cost experiment."""
import numpy as np


def native(gc, facts, sts):
    """Read native deck/relic objects; no neural observation indices."""
    types = ('ATTACK', 'SKILL', 'POWER', 'CURSE', 'STATUS')
    costs = (-2, -1, 0, 1, 2, 3, 4)
    hist = np.zeros((len(types), len(costs)), dtype=np.float64)
    deck = list(gc.deck)
    for card in deck:
        row = facts['faces'][2*int(card.id)+int(card.upgraded)]
        assert row['type'] == card.type.name
        hist[types.index(card.type.name), costs.index(row['printed_cost'])] += 1/len(deck)
    owned = {item.id.name for item in gc.relics}
    energy = ('MARK_OF_PAIN', 'ECTOPLASM', 'PHILOSOPHERS_STONE', 'RUNIC_DOME',
              'SOZU', 'VELVET_CHOKER', 'BUSTED_CROWN', 'COFFEE_DRIPPER', 'CURSED_KEY', 'FUSION_HAMMER')
    contexts = (1., sum(name in owned for name in energy)/3., float('SNECKO_EYE' in owned),
        float('MUMMIFIED_HAND' in owned), float(any(c.id == sts.CardId.CORRUPTION for c in deck)),
        float('RUNIC_PYRAMID' in owned))
    return np.concatenate([hist.ravel()*value for value in contexts]).astype(np.float32)


def matrix(base, shape, facts):
    """Dense NumPy implementation independent of the sparse scatter kernel."""
    counts = base[:, shape['face_columns']].astype(np.float64)*20.
    total = counts.sum(axis=1)
    assert np.all(total > 0)
    hist = np.zeros((len(base), 35), dtype=np.float64)
    types, costs = ('ATTACK', 'SKILL', 'POWER', 'CURSE', 'STATUS'), (-2, -1, 0, 1, 2, 3, 4)
    for face, row in enumerate(facts['faces']):
        if row['type'] not in types or row['printed_cost'] is None:
            assert not np.any(counts[:, face])
            continue
        target = 7*types.index(row['type'])+costs.index(row['printed_cost'])
        hist[:, target] += counts[:, face]/total
    contexts = np.column_stack((np.ones(len(base)), base[:, shape['energy_columns']].sum(1)/3.,
        base[:, shape['relic_columns'][0]], base[:, shape['relic_columns'][1]],
        base[:, shape['corruption_columns']].sum(1) > 0, base[:, shape['relic_columns'][2]]))
    extra = np.concatenate([hist*contexts[:, [i]] for i in range(6)], axis=1)
    return np.concatenate((base, extra.astype(np.float32)), axis=1)
