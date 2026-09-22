"""Check new targets against graph/raw endpoints and native old-route replays."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_combat_pretraining as P
    I, O, E = P.I, P.O, P.E
    plan = P.registered(root)
    torch.set_num_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = P.Data(store, root / 'data')
    exit_proof = E.read(root / 'prepare-control/exit.json')
    assert exit_proof['status'] == 'prepare_complete' and exit_proof['exit_code'] == 0
    owned = E.read(root / 'prepare-execution/pipeline-process-exit.json')
    assert owned['exit_code'] == 0 and owned['cleanup']['clean']
    assert len(set(data.edges)) == len(data.edges)
    assert {f['seed'] for f in data.families} == {f['seed'] for f in store.families}
    by_edge = {int(e): i for i, e in enumerate(data.edges)}
    assert all(len(set(data.seed[f['indices']])) == 1 for f in data.families)
    graph_root = Path(plan['graph_source'])
    x = O.C.D.runtime(plan['runtime'])
    counts = Counter()
    # Recompute every target by a separate endpoint reader. Terminal HP comes
    # from bound raw episodes, never from the terminal graph's masked next row.
    for family in store.families:
        graph = E.read(graph_root / 'families' / f'{family["seed"]}.json.gz')
        terminal = {}
        for route in graph['routes']:
            local = route['edges'][-1][1]
            if family['edge_begin'] + local not in by_edge:
                continue
            assert E.sha(route['path']) == route['sha256']
            raw = E.read(route['path'])
            value = (raw['hp'], raw['status'])
            assert local not in terminal or terminal[local] == value
            terminal[local] = value
        wanted = set()
        for local, edge in enumerate(graph['edges']):
            state = graph['states'][edge['state']]
            descriptor = dict(state['descriptors'][edge['action']])
            rooms = [r for r in (0, 1, 6) if descriptor.get(x.A.OFF_MROOM + r, 0) == 1]
            if descriptor.get(x.A.OFF_ACTION + x.A.AK_MAP, 0) != 1 or len(rooms) != 1:
                continue
            global_edge = family['edge_begin'] + local
            wanted.add(global_edge)
            row_id = by_edge[global_edge]
            before = dict(state['observation'])
            current = round(before.get(store.spec['observations'].index(0), 0) * 200.)
            maximum = round(before[store.spec['observations'].index(1)] * 200.)
            if edge['done']:
                after, status = terminal[local]
                alive = status != 'death'
                counts['terminal_' + status] += 1
            else:
                nxt = dict(graph['states'][edge['next_state']]['observation'])
                after = nxt.get(store.spec['observations'].index(0), 0) * 200.
                alive = True
                counts['nonterminal'] += 1
            expected = [(after - current) / maximum, float(alive)]
            np.testing.assert_allclose(data.targets[row_id], expected, atol=1e-6)
            assert data.seed[row_id] == family['seed'] and data.act[row_id] == state['act']
            assert data.room[row_id] == rooms[0] and data.hp_bin[row_id] == min(3, int(4 * current / maximum))
        present = {int(e) for e in data.edges[data.seed == family['seed']]}
        assert wanted == present
    # Native endpoint checks use one accepted route of each terminal kind.
    refs = E.read(Path(plan['failure_profile']).parent / 'heart-e143-continuous-transitions-20260922-01/fit-references.json')
    refs = [next(r for r in refs if r['status'] == status) for status in ('heart_win', 'death', 'act3_without_heart')]
    parent = E.parent_model(x)
    native = Counter()
    for reference in refs:
        run = E.read(reference['path'])
        assert E.sha(reference['path']) == reference['sha256']
        family = next(f for f in store.families if f['seed'] == reference['seed'])
        graph = E.read(graph_root / 'families' / f'{family["seed"]}.json.gz')
        state_ids = {s['fingerprint']: i for i, s in enumerate(graph['states'])}
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
        pending = None
        def finish(terminal=False):
            nonlocal pending
            if pending is None:
                return
            index, before, maximum, battles = pending
            expected = [(gc.cur_hp - before) / maximum, float(not (terminal and run['status'] == 'death'))]
            np.testing.assert_allclose(data.targets[index], expected, atol=1e-6)
            assert data.battle_count[index] == battles and battles > 0
            native['endpoints'] += 1
            native[f'battle_span_{battles}'] += 1
            if terminal:
                native[run['status']] += 1
            pending = None
        for step in run['prefix']:
            x.R.clock_input(gc, x.config)
            assert x.R.fingerprint(gc) == step['before']
            if step['kind'] == 'outside':
                finish()
                local = state_ids[step['before']]
                state = graph['states'][local]
                choice = state['actions'].index(step['action'])
                global_state = family['begin'] + local
                u, v = store.state_edge_ptr[global_state:global_state + 2]
                candidates = store.state_edge_ids[u:v]
                edge = candidates[store.edge_action[candidates] == store.menu_ptr[global_state] + choice]
                assert len(edge) == 1
                if int(edge[0]) in by_edge:
                    index = by_edge[int(edge[0])]
                    assert P.hp(state, store.spec) == gc.cur_hp and P.hp(state, store.spec, True) == gc.max_hp
                    actions = list(x.R.sts.get_legal_game_actions(gc))
                    _, descriptors, _ = x.A.build_choices(gc)
                    observation = x.A.obs_vec(gc)
                    chosen_parent = parent.choose(gc, observation, actions, descriptors)
                    assert chosen_parent == state['parent']
                    public = dict(observation=x.R.sparse([observation[i] for i in store.spec['observations']]), descriptors=[x.R.sparse(d) for d in descriptors])
                    expected = np.zeros(store.spec['width'] + store.spec['descriptor_dim'], dtype=np.float32)
                    for col, value in O.C.sparse_features(public, choice, store.spec):
                        expected[col] = value
                    expected[store.spec['width']:] = descriptors[chosen_parent]
                    table = I.paired_features(store, np.array([global_state]), np.array([store.menu_ptr[global_state] + choice])).to_dense().numpy()[0]
                    np.testing.assert_allclose(table, expected, atol=1e-6)
                    pending = [index, gc.cur_hp, gc.max_hp, 0]
                    native['inputs'] += 1
                    native[f'act_{gc.act}'] += 1
            else:
                if pending is not None:
                    pending[3] += 1
            x.R.replay_step(gc, step, x.config)
        x.R.clock_input(gc, x.config)
        finish(True)
        x.P.verify_terminal(gc, run)
    # Actual data cannot cross the outer family boundary during either stage.
    denied = 0
    for fold in range(3):
        allowed = {f['seed'] for f in data.families if O.T.fold(f['seed']) != fold}
        held = next(f for f in data.families if O.T.fold(f['seed']) == fold)
        try:
            data.batch(held['indices'][:1], allowed)
        except ValueError as error:
            assert 'held family' in str(error)
            denied += 1
        else:
            raise AssertionError('held auxiliary labels admitted')
    result = dict(status='complete_reviewed', data_completion_sha256=E.sha(root / 'data/completion.json'),
        runner_sha256=E.sha(P.__file__), reviewer_sha256=E.sha(__file__), targets_recomputed=len(data.edges),
        terminal_counts=dict(counts), native_checks=dict(native), held_access_rejections=denied,
        owned_exit_sha256=E.sha(root / 'prepare-execution/pipeline-process-exit.json'), new_games=0, optimizer_updates=0)
    E.write(root / 'data-review.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
