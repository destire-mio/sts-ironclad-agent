"""Read printed card costs from controlled instances of the frozen engine.

These isolated metadata fixtures perform no search or continuation and are
never training rows. They do not establish parity with the original game.
"""
import argparse
from pathlib import Path
import sys


def main(root):
    sys.path.insert(0, str(root/'program'))
    import heart_cost_relations_value as L
    E, O = L.E, L.O
    plan = E.read(root/'protocol.json'); x = O.C.D.runtime(plan['runtime'])
    seed = E.read(Path(plan['natural_source'])/'fit-roles.json')[0]
    def initial():
        return x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, seed, 20)
    def battle(gc):
        before = x.R.fingerprint(gc); bc = x.R.sts.BattleContext()
        bc.init_encounter(gc, x.R.sts.MonsterEncounter.CULTIST)
        assert before == x.R.fingerprint(gc)
        return bc
    faces = []; fixtures = 0
    for identity in range(x.A.CARD_CAP):
        for upgraded in (False, True):
            card = x.R.sts.Card(x.R.sts.CardId(identity))
            if upgraded: card.upgrade()
            row = dict(id=identity, name=card.id.name, upgraded=upgraded, type=card.type.name)
            # Native permanent decks do not accept STATUS cards. Do not inject
            # an impossible fixture or fabricate costs for unused deck faces;
            # preparation must reject any real row containing such a face.
            if row['type'] not in L.TYPES or row['type'] == 'STATUS':
                row['printed_cost'] = None
            else:
                gc = initial(); gc.obtain_card(card); bc = battle(gc)
                cards = list(bc.hand)+list(bc.draw_pile)+list(bc.discard_pile)+list(bc.exhaust_pile)
                values = {c.base_cost for c in cards if int(c.id) == identity and bool(c.upgraded) == upgraded}
                assert len(values) == 1, row
                row['printed_cost'] = values.pop(); assert row['printed_cost'] in L.COSTS, row
                fixtures += 1
            faces.append(row)
    energy = []
    for name in L.ENERGY:
        gc = initial(); gc.obtain_relic(getattr(x.R.sts.RelicId, name)); bc = battle(gc)
        assert bc.player.energy_per_turn == 4, name
        energy.append(dict(name=name, observed_energy_per_turn=4))
        fixtures += 1
    assert battle(initial()).player.energy_per_turn == 3
    # Check changing upgrade costs and separate X/unplayable bins explicitly.
    expected = {'CLASH': [0, 0], 'BLUDGEON': [3, 3], 'CORRUPTION': [3, 2],
                'BODY_SLAM': [1, 0], 'WHIRLWIND': [-1, -1], 'BLOOD_FOR_BLOOD': [4, 3],
                'ASCENDERS_BANE': [-2, -2], 'DARK_EMBRACE': [2, 1], 'MADNESS': [1, 0]}
    for name, costs in expected.items():
        i = int(getattr(x.R.sts.CardId, name))
        assert [faces[2*i+j]['printed_cost'] for j in (0, 1)] == costs
    result = dict(version=L.VERSION, engine_sha256=x.identity['engine_sha256'], faces=faces,
        energy_relic_checks=energy, controlled_metadata_fixtures=fixtures+1,
        new_games=0, MCTS_calls=0, optimizer_updates=0,
        limits='Printed base costs with starter relic only; not effective costs after Snecko, Corruption or other combat effects. Cost metadata for unused other-color cards is not an original-game alignment claim.')
    E.write(root/'card-facts.json', result)
    store = O.Store(Path(plan['learning_source'])/'store')
    E.write(root/'layout.json', L.layout(store.spec, x, result))
    print(dict(faces=len(faces), metadata_fixtures=fixtures+1, facts_sha256=E.sha(root/'card-facts.json')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
