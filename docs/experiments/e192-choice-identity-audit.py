"""Classify first greedy interventions without assuming RNG equivalence.

Matching public action descriptors after removing raw indices is only an
observational alias. It does not authorize merging actions, outcomes or RNG.
"""
import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root/'program'))
    import heart_greedy_policy_evaluation as L
    E = L.E
    plan = L.registered(root)
    torch.set_num_threads(1)
    x = L.G.C.D.runtime(plan['runtime'])
    bound = E.read(root/'choice-identity-registration.json')
    assert bound['auditor_sha256'] == E.sha(__file__)
    for path, digest in bound['hashes'].items():
        assert E.sha(path) == digest
    source = Path(plan['learning_source'])
    roles = E.read(source/'roles-private.json')
    refs = E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'), 'seed', 'reference')
    assignments = E.read(root/'assignments-private.json')
    certificate = E.read(source/'greedy-path-audit-private.json')
    policy = L.policy_from(x, plan['candidate'], plan['candidate_sha256'])
    kinds = {value: name.removeprefix('AK_') for name, value in vars(x.A).items() if name.startswith('AK_')}
    counts = Counter()
    by_kind = Counter()
    aliases_by_kind = Counter()
    outcome_groups = Counter()
    rows = []
    keep = np.ones(x.A.DESC_DIM, dtype=bool)
    keep[x.A.OFF_RAW_INDEX:x.A.OFF_RAW_INDEX+x.A.W_RAW_INDEX] = False
    for index in assignments['changed']:
        seed = roles['evaluation'][index]
        reference = refs[seed]
        assert E.sha(reference['path']) == reference['sha256']
        old = E.read(reference['path'])
        path = root/f'evaluation/candidate/{index}.json.gz'
        new = E.read(path)
        assert E.sha(path) == E.read(root/'evaluation/completion.json')['hashes'][str(path.relative_to(root/'evaluation'))]
        assert old['seed'] == new['seed'] == seed and not new.get('error')
        j = certificate['paths'][index]['first_change']['prefix_index']
        assert old['prefix'][:j] == new['prefix'][:j]
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, seed, 20)
        for step in old['prefix'][:j]:
            x.R.replay_step(gc, step, x.config)
            counts['native_prefix_steps'] += 1
        x.R.clock_input(gc, x.config)
        before = x.R.fingerprint(gc)
        assert before == old['prefix'][j]['before'] == new['prefix'][j]['before']
        actions = list(x.R.sts.get_legal_game_actions(gc))
        _, descriptors, _ = x.A.build_choices(gc)
        previous = next(i for i, action in enumerate(actions) if int(action.bits) == old['prefix'][j]['action'])
        chosen = policy.choose(gc, x.A.obs_vec(gc), actions, descriptors)
        assert int(actions[chosen].bits) == new['prefix'][j]['action'] and before == x.R.fingerprint(gc)
        policy.samples.clear()
        a, b = np.asarray(descriptors[previous]), np.asarray(descriptors[chosen])
        kind = kinds[x.R.kind(descriptors[chosen])]
        index_only = bool(np.array_equal(a[keep], b[keep]))
        counts['first_interventions'] += 1
        counts['index_only_descriptors' if index_only else 'other_public_descriptor_changes'] += 1
        by_kind[kind] += 1
        if index_only:
            aliases_by_kind[kind] += 1
        outcome = ('both_win' if old['status'] == new['status'] == 'heart_win' else
                   'candidate_only' if new['status'] == 'heart_win' else
                   'baseline_only' if old['status'] == 'heart_win' else 'both_fail')
        outcome_groups[('index_only:' if index_only else 'other:')+outcome] += 1
        card_slice = slice(x.A.OFF_CARD, x.A.OFF_CARD+x.A.W_CARD)
        rows.append(dict(evaluation_index=index, first_kind=kind, raw_indices_only=index_only,
            same_card_id=bool(np.array_equal(a[card_slice], b[card_slice])),
            original_status=old['status'], candidate_status=new['status'],
            changed_descriptor_columns=np.flatnonzero(a != b).tolist()))
    assert counts['first_interventions'] == 48
    result = dict(status='complete', experiment='E192', retrospective=True,
        counts=dict(counts), first_action_kinds=dict(by_kind), aliases_by_kind=dict(aliases_by_kind),
        observed_full_policy_outcome_groups=dict(outcome_groups), new_games=0, optimizer_updates=0,
        source_completion_sha256=E.sha(root/'evaluation/completion.json'),
        auditor_sha256=E.sha(__file__), registration_sha256=E.sha(root/'choice-identity-registration.json'),
        limits='First changed decision only. Equality after masking three raw-index descriptor coordinates is not complete game-state or RNG equivalence. Later decisions also differ; outcome groups do not isolate a causal effect of this first choice. No feature masking, action merging, new policy, or new continuation follows from this audit.')
    E.write(root/'choice-identity-audit-private.json', dict(result=result, paths=rows))
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
