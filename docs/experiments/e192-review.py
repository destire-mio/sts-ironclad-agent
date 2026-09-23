"""Recompute the fixed greedy evaluation, including all reused-route roles."""
import argparse
from collections import Counter
import math
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root/'program'))
    import heart_greedy_policy_evaluation as L
    E = L.E
    torch.set_num_threads(1)
    plan = L.registered(root)
    bound = E.read(root/'review-registration.json')
    assert bound['reviewer_sha256'] == E.sha(__file__)
    for path, digest in bound['hashes'].items():
        assert E.sha(path) == digest
    x = L.G.C.D.runtime(plan['runtime'])
    source = Path(plan['learning_source'])
    roles = E.read(source/'roles-private.json')
    assignment = E.read(root/'assignments-private.json')
    preflight = E.read(root/'preflight.json')
    assert preflight['status'] == 'passed' and preflight['candidate_sha256'] == plan['candidate_sha256']
    assert preflight['counts']['unchanged_complete_routes'] == 80 and preflight['counts']['changed_routes'] == 48
    certificate = E.read(source/'greedy-path-audit-private.json')
    refs = E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'), 'seed', 'reference')
    out = root/'evaluation'
    E.proof(out, 'completion.json')
    report = E.read(out/'report.json')
    policy = L.policy_from(x, plan['candidate'], plan['candidate_sha256'])
    theta, initial = policy.net.state_dict(), policy.initial.state_dict()
    totals = Counter()
    maximum = 0.
    used = set()

    def forward(state, values):
        hidden = np.maximum(np.matmul(values, state['0.weight'].numpy().T)+state['0.bias'].numpy(), 0.)
        return np.sum(hidden*state['2.weight'].numpy(), axis=1)+state['2.bias'].numpy()[0]

    def verify(index, control=False):
        nonlocal maximum
        seed = roles['evaluation'][index]
        path = out/('controls' if control else 'candidate')/f'{index}.json.gz'
        run = E.read(path)
        used.add(str(path.resolve()))
        assert run['seed'] == seed and run['status'] in ('heart_win', 'death', 'act3_without_heart') and not run.get('error')
        assert run['checkpoint_sha256'] == plan['candidate_sha256'] and run['engine_sha256'] == x.identity['engine_sha256']
        assert run['execution_rule'] == 'learned_greedy_parent_ties'
        assert run['search_budget'] == dict(simulations=8000, boss_multiplier=3, max_replans=256)
        reference = E.read(refs[seed]['path'])
        assert E.sha(refs[seed]['path']) == refs[seed]['sha256']
        assert reference['seed'] == seed and reference['status'] == refs[seed]['status']
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, seed, 20)
        choices = 0
        bosses, fourth = [], []
        changes = Counter()
        for step in run['prefix']:
            x.R.clock_input(gc, x.config)
            before = x.R.fingerprint(gc)
            assert before == step['before']
            if step['kind'] == 'outside':
                actions = list(x.R.sts.get_legal_game_actions(gc))
                _, descriptors, _ = x.A.build_choices(gc)
                features, scores, active, parent, _ = policy.menu(gc, x.A.obs_vec(gc), actions, descriptors)
                values = features.numpy()
                logits = scores+forward(theta, values)-forward(initial, values)
                row = run['policy_samples'][choices]
                maximum = max(maximum, float(np.abs(logits-row['logits']).max()))
                np.testing.assert_allclose(logits, row['logits'], rtol=0, atol=1e-9)
                maximum_score = max(float(v) for v in logits)
                tied = [int(i) for i, v in zip(active, logits, strict=True) if maximum_score-float(v) <= 1e-9]
                selected = parent if parent in tied else tied[0]
                assert row['chosen'] == selected and row['parent'] == parent and row['active'] == active.tolist()
                assert int(actions[selected].bits) == step['action'] and int(x.R.kind(descriptors[selected])) == row['action_kind']
                assert before == x.R.fingerprint(gc)
                if selected != parent:
                    changes[f'{gc.act}:{row["action_kind"]}'] += 1
                choices += 1
            else:
                if gc.act == 3 and gc.cur_room == x.R.sts.Room.BOSS:
                    bosses.append(gc.encounter.name)
                if gc.act == 4:
                    assert gc.red_key and gc.green_key and gc.blue_key
                    fourth.append(gc.encounter.name)
            x.R.replay_step(gc, step, x.config)
        x.R.clock_input(gc, x.config)
        x.P.verify_terminal(gc, run)
        audit = run['audit']
        assert audit['public_inputs_actions_state_rng_and_terminal_verified']
        assert choices == len(run['policy_samples']) == audit['outside_choices'] and dict(changes) == audit['changes']
        if run['status'] == 'heart_win':
            assert len(bosses) == len(set(bosses)) == 2 and fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']
        assert run['first_change'] == L.G.N.first_change(x, reference, run)
        if control:
            assert run['prefix'] == reference['prefix'] and x.P.terminal_signature(run) == x.P.terminal_signature(reference)
        else:
            assert run['first_change'] == dict(kind='noncombat', prefix_index=certificate['paths'][index]['first_change']['prefix_index'])
            if run['status'] == 'heart_win':
                repeated_path = path.parent/'repeated'/path.name
                repeated = E.read(repeated_path)
                used.add(str(repeated_path.resolve()))
                assert repeated.get('fresh_replan_matched') and repeated['status'] == 'heart_win' and not repeated.get('error')
                for key in ('seed', 'prefix', 'policy_samples', 'checkpoint_sha256', 'engine_sha256', 'execution_rule', 'audit'):
                    assert repeated[key] == run[key]
                assert x.P.terminal_signature(repeated) == x.P.terminal_signature(run)
                totals['winner_replans'] += 1
        totals['native_routes'] += 1
        totals['outside_choices'] += choices
        totals['native_steps'] += len(run['prefix'])
        return int(run['status'] == 'heart_win')

    for index in assignment['controls']:
        verify(index, True)
    old = []
    for index, seed in enumerate(roles['evaluation']):
        assert E.sha(refs[seed]['path']) == refs[seed]['sha256']
        status = E.read(refs[seed]['path'])['status']
        assert status == refs[seed]['status'] == certificate['paths'][index]['parent_status']
        old.append(int(status == 'heart_win'))
    candidate = old.copy()
    for index in assignment['changed']:
        candidate[index] = verify(index)
    counts = Counter('both_win' if a and b else 'candidate_only' if b else 'baseline_only' if a else 'both_fail'
                     for a, b in zip(old, candidate, strict=True))
    n = counts['candidate_only']+counts['baseline_only']
    p = min(1., 2*sum(math.comb(n, i) for i in range(min(counts['candidate_only'], counts['baseline_only'])+1))/2**n) if n else 1.
    comparison = dict(assigned=128, baseline_wins=sum(old), candidate_wins=sum(candidate),
                      net_gain=sum(candidate)-sum(old), paired=dict(counts), exact_p=p)
    assert comparison == report['comparison']
    assert report['learning_gate_passed'] == (comparison['net_gain'] >= 8 and p < .025)
    assert report['base_games'] == totals['native_routes'] == 52
    assert report['winner_replans'] == totals['winner_replans']
    assert report['new_games'] == 52+totals['winner_replans'] <= 100
    assert report['changed_routes_evaluated'] == 48 and report['unchanged_routes_reused'] == 80 and report['unchanged_controls'] == 4
    assert report['optimizer_updates'] == report['unused_acceptance_games'] == 0 and report['source_optimizer_updates'] == 3444
    assert not report['policy_adoption'] and report['zero_faults'] and report['candidate_sha256'] == plan['candidate_sha256']
    assert used == {str(p.resolve()) for p in out.rglob('*.json.gz')}
    control = E.read(root/'control/exit.json')
    owned = E.read(root/'eval-execution/pipeline-process-exit.json')
    assert control['status'] == 'complete' and control['exit_code'] == owned['exit_code'] == 0 and owned['cleanup']['clean']
    assert control['completion_sha256'] == E.sha(out/'completion.json')
    assert control['owned_exit_sha256'] == E.sha(root/'eval-execution/pipeline-process-exit.json')
    result = dict(status='complete_reviewed', experiment='E192', result=report, counts=dict(totals),
        maximum_numpy_logit_error=maximum, all_new_base_routes_natively_rechecked=True,
        reused_route_roles_and_prior_certificate_verified=True, process_cleanup_verified=True,
        registration_sha256=E.sha(root/'registration.json'), completion_sha256=E.sha(out/'completion.json'),
        reviewer_sha256=E.sha(__file__), policy_adoption=False, limits=plan['limits'])
    E.write(root/'result-review.json', result)
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
