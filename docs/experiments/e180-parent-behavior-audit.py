"""Describe the actual old parent policy, without new games or fitting.

All natural actions are matched to the admitted graph and their recorded
outcomes. A hash-selected native subset separates heuristic recommendations,
network corrections and the first-boss wrapper. Associations are not causes.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import sys


def main(repository, output):
    sys.path.insert(0, str(repository / 'agent'))
    import heart_early_card_scope as E
    import heart_continuous_data as C
    source = repository / 'runs/heart-e143-continuous-transitions-20260922-01'
    graph_source = repository / 'runs/heart-e153-existing-control-data-20260922-01'
    references = E.read(source / 'fit-references.json')
    assert len(references) == 1536
    assert [r['seed'] for r in references] == E.read(source / 'fit-roles.json')
    proof = E.read(graph_source / 'completion-verification.json')
    assert proof['status'] == 'complete'
    x = E.load_runtime(source / 'runtime'); model = E.parent_model(x)
    assert model.model_type == 'first_boss_relic_ranker'
    assert model.base.model_type == 'card_context_residual' and model.base.prior_strength == 3.
    selected = set(sorted((r['seed'] for r in references), key=lambda seed:
        (hashlib.sha256(('E180-native-audit:'+str(seed)).encode()).hexdigest(), seed))[:64])
    spec = C.spec_for(x)
    kinds = {v: k.removeprefix('AK_') for k, v in vars(x.A).items() if k.startswith('AK_')}
    rooms = {v: k.name for k, v in x.A.ROOM_IDX.items()}
    output.mkdir()
    E.write(output / 'registration.json', dict(experiment='E180', runner_sha256=E.sha(__file__),
        reference_sha256=E.sha(source / 'fit-references.json'),
        graph_proof_sha256=E.sha(graph_source / 'completion-verification.json'),
        runtime_identity=x.identity, families=1536, native_subset=64,
        native_selection='First64 families ordered by sha256(E180-native-audit:+seed), before outcome inspection.',
        scope='Natural parent only; every old action/state/terminal joined to admitted graph. Native subset replays saved actions to compare heuristic, neural residual and first-boss wrapper. No alternative simulation or learning.',
        new_games=0, optimizer_updates=0))
    counts = defaultdict(Counter); native = defaultdict(Counter)
    maps = defaultdict(Counter); rests = defaultdict(Counter); cards = defaultdict(Counter)
    bosses = defaultdict(Counter); per_family = []; native_steps = 0

    def kind(d):
        hits = [i for i, v in d.items() if 0 <= i < x.A.W_ACTION and v == 1.]
        assert len(hits) == 1
        return hits[0]

    def slot(d, start, width):
        hits = [i-start for i, v in d.items() if start <= i < start+width and v == 1.]
        assert len(hits) == 1
        return hits[0]

    for number, ref in enumerate(references):
        path = graph_source / 'families' / f"{ref['seed']}.json.gz"
        assert E.sha(path) == proof['hashes'][str(path)]
        assert E.sha(ref['path']) == ref['sha256']
        graph, run = E.read(path), E.read(ref['path'])
        assert graph['status'] == 'complete' and graph['seed'] == run['seed'] == ref['seed']
        assert run['target'] == ref['target'] == int(run['status'] == 'heart_win')
        assert run['checkpoint_sha256'] == x.identity['model_sha256']
        assert run['engine_sha256'] == x.identity['engine_sha256'] and not run.get('error')
        states = graph['states']; by_fp = {s['fingerprint']: i for i, s in enumerate(states)}
        assert len(by_fp) == len(states)
        edges = defaultdict(dict)
        for edge in graph['edges']:
            assert edge['action'] not in edges[edge['state']]
            edges[edge['state']][edge['action']] = edge
        outside = [(i, step) for i, step in enumerate(run['prefix']) if step['kind'] == 'outside']
        indices = [by_fp[step['before']] for _, step in outside]
        exposure = Counter()
        for position, ((prefix, step), index) in enumerate(zip(outside, indices)):
            row = states[index]; parent = row['parent']; actions = row['actions']
            assert actions[parent] == step['action']
            edge = edges[index][parent]
            if position + 1 < len(indices):
                assert not edge['done'] and edge['next_state'] == indices[position+1]
            else:
                assert edge['done'] and edge['reward'] == ref['target']
            ds = [dict(d) for d in row['descriptors']]; d = ds[parent]
            ks = [kind(d) for d in ds]; k = ks[parent]; name = kinds[k]
            total = counts[name]; total['decisions'] += 1
            total['multiple_legal_actions'] += len(actions) > 1
            total['multiple_recorded_actions'] += len(edges[index]) > 1
            total['legal_actions'] += len(actions); total['recorded_actions'] += len(edges[index])
            act = str(row['act']); observation = dict(row['observation'])
            hp = observation.get(spec['observations'].index(0), 0.)
            max_hp = observation[spec['observations'].index(1)]
            if k == x.A.AK_MAP:
                room = rooms[slot(d, x.A.OFF_MROOM, x.A.W_ROOM)]
                maps[act]['chosen_'+room] += 1; exposure['act'+act+'_'+room] += 1
                options = {rooms[slot(q, x.A.OFF_MROOM, x.A.W_ROOM)] for q, qk in zip(ds, ks) if qk == x.A.AK_MAP}
                if 'ELITE' in options and len(options) > 1:
                    bucket = maps[act]; bucket['elite_or_other'] += 1; bucket['elite_chosen_when_other'] += room == 'ELITE'
                    if hp/max_hp >= .8:
                        bucket['healthy_elite_or_other'] += 1
                        bucket['healthy_elite_chosen'] += room == 'ELITE'
            elif k == x.A.AK_REST:
                option = slot(d, x.A.OFF_REST, x.A.W_REST)
                rests[act]['chosen_'+str(option)] += 1
                if option == 0 and hp/max_hp >= .8: rests[act]['rest_at_least_80pct_hp'] += 1
            if set(ks) <= {x.A.AK_REWARD_CARD, x.A.AK_REWARD_SKIP, x.A.AK_REWARD_SINGING_BOWL} and x.A.AK_REWARD_CARD in ks:
                cards[act][name] += 1
            if k == x.A.AK_BOSS_RELIC:
                relic = x.R.sts.RelicId(slot(d, x.A.OFF_RELIC, x.A.W_RELIC)).name
                bosses[act][relic] += 1
            elif k == x.A.AK_BOSS_SKIP: bosses[act]['SKIP'] += 1
        per_family.append(dict(seed=ref['seed'], target=ref['target'], decisions=len(indices), exposure=dict(exposure)))
        if ref['seed'] in selected:
            gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, ref['seed'], 20)
            for step in run['prefix']:
                x.R.clock_input(gc, x.config)
                assert x.R.fingerprint(gc) == step['before']
                if step['kind'] == 'outside':
                    actions = list(x.R.sts.get_legal_game_actions(gc)); _, ds, _ = x.A.build_choices(gc)
                    obs = x.A.obs_vec(gc); row = states[by_fp[step['before']]]
                    assert [int(a.bits) for a in actions] == row['actions']
                    assert [x.R.sparse(d) for d in ds] == row['descriptors']
                    assert x.R.sparse([obs[i] for i in spec['observations']]) == row['observation']
                    with x.H.torch.no_grad():
                        teacher = x.R.heuristic_choice(gc, actions, ds)
                        logits = model.base.score(x.H.torch.tensor(obs), ds)
                        base = int(model.base.with_prior(logits, teacher).argmax())
                        chosen = model.choose(gc, obs, actions, ds)
                    assert chosen == row['parent'] and int(actions[chosen].bits) == step['action']
                    assert x.R.fingerprint(gc) == step['before']
                    name = kinds[x.R.kind(ds[chosen])]; bucket = native[name]
                    bucket['decisions'] += 1; bucket['multi_action'] += len(actions) > 1
                    bucket['network_changed_heuristic'] += base != teacher
                    bucket['wrapper_changed_network'] += chosen != base
                    bucket['final_changed_heuristic'] += chosen != teacher
                x.R.replay_step(gc, step, x.config); native_steps += 1
            x.R.clock_input(gc, x.config); x.P.verify_terminal(gc, run)
        if (number+1) % 256 == 0: print(dict(families=number+1, native_saved_steps=native_steps), flush=True)
    E.write(output / 'families-private.json', per_family)
    report = dict(status='complete', experiment='E180', families=1536, parent_wins=sum(r['target'] for r in references),
        parent_type=model.model_type, base_type=model.base.model_type, prior_strength=model.base.prior_strength,
        actions=dict(counts), mapped_routes_by_act=dict(maps), campfires_by_act=dict(rests),
        pure_card_menus_by_act=dict(cards), boss_relic_choices_by_act=dict(bosses),
        native_audited_families=64, native_saved_steps=native_steps, native_policy_components=dict(native),
        all_natural_actions_graph_edges_and_terminals_matched=True,
        native_choices_observations_state_and_rng_matched=True, new_games=0, optimizer_updates=0,
        limits='Descriptive old development trajectories. Decision exposures are correlated within families. Missing exact-state action outcomes do not prove absence of similar training states. Routing, HP and card associations do not establish causes or counterfactual wins. The64 native families are an outcome-independent audit subset, not the entire population.')
    E.write(output / 'report.json', report)
    E.write(output / 'completion.json', dict(status='complete', hashes={p.name:E.sha(p) for p in output.iterdir() if p.is_file()}))
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); main(args.repository.resolve(), args.output.resolve())
