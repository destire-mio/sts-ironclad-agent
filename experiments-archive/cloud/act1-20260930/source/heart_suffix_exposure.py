#!/usr/bin/env python3
"""Extend one verified full-suffix policy update, retaining its exact optimizer prefix."""
import argparse
from collections import Counter
import copy
from pathlib import Path
import shutil

import heart_suffix_policy as U
import heart_suffix_audit as V

E, P, H, S, L = U.E, U.P, U.H, U.S, U.L


def prepare(root, source):
    assert not root.exists()
    S.verify_files(source)
    L.verify_runtime(source)
    decision = H.read_json(source / 'decision.json')
    assert decision['experiment'] == 'E36' and decision['status'] == 'complete'
    assert not decision['development_gate_passed'], 'a passing E36 candidate must receive its fresh test first'
    proof = H.read_json(source / 'completion-verification.json')
    assert proof['status'] == 'complete'
    for name, sha in proof['hashes'].items():
        assert S.sha(source / name) == sha
    training = H.read_json(source / 'training-report.json')
    assert training['status'] == 'complete' and not training['stopped_for_low_fit_signal']
    assert [x['iteration'] for x in training['iterations']] == [0, 1, 2]
    for item in training['iterations']:
        for name, sha in item['hashes'].items():
            assert S.sha(source / f'iterations/{item["iteration"]}' / name) == sha
    checkpoint = H.torch.load(source / 'candidate.pt', map_location='cpu', weights_only=True)
    assert H.state_hash(H.load_scorer(checkpoint)) == checkpoint['state_hash']
    assert S.sha(source / 'candidate.pt') == training['checkpoint_sha256']
    diagnostic = H.read_json(source / 'update-magnitude-diagnostics.json')
    assert diagnostic['status'] == 'complete' and diagnostic['holdout_decisions'] == 0
    for item in diagnostic['iterations']:
        assert S.sha(source / f'iterations/{item["iteration"]}/candidate.pt') == item['candidate_sha256']
    E.copy_runtime(source, root)
    for module, name in ((E, 'heart_data_scale.py'), (U, 'run_suffix_policy.py'),
                         (V, 'heart_suffix_audit.py'), (U.V, 'heart_data_scale_audit.py')):
        shutil.copy2(module.__file__, root / name)
    shutil.copy2(U.__file__, root / 'heart_suffix_policy.py')
    shutil.copy2(__file__, root / 'run_suffix_exposure.py')
    shutil.copy2(Path(__file__).with_name('heart_suffix_exposure_pipeline.py'), root / 'run_experiment.py')
    for name in ('identity.json', 'roots.json', 'seeds.json', 'references.json', 'seed-roles.json'):
        shutil.copy2(source / name, root / name)
    dst = root / 'iterations/0'
    dst.mkdir(parents=True)
    evidence = []
    # Keep inherited evidence byte-for-byte. Its recorded iteration remains 2;
    # local directory 0 is the one update slot of this new experiment.
    for name in ('plan.json', 'collection-report.json', 'results-index.json', 'label-verification.json'):
        old = source / 'iterations/2' / name
        shutil.copy2(old, dst / name)
        evidence.append({'source': str(old), 'copied_path': f'iterations/0/{name}', 'sha256': S.sha(old)})
    old_plan = H.read_json(source / 'plan.json')
    plan = copy.deepcopy(old_plan)
    plan.update(experiment='E37', created_at=P.utc(), source=str(source),
        source_decision_sha256=S.sha(source / 'decision.json'),
        source_completion_sha256=S.sha(source / 'completion-verification.json'),
        source_training_sha256=S.sha(source / 'training-report.json'),
        source_update_diagnostics_sha256=S.sha(source / 'update-magnitude-diagnostics.json'),
        source_iteration=2, iterations=1,
        exposure_control='Report paired eight-pass versus E36 two-pass whole-game results on the same 1024 roots, in addition to the unchanged adoption gate against the original network.',
        hypothesis='E36 endpoint diagnostics show limited probability movement after two passes. Replay the identical final-batch optimizer path for eight passes to test additional use of these current-policy returns, without new labels, architecture or feature changes.',
        stopping='Exactly eight complete passes of the third E36 collection. First two passes must reproduce every E36 final weight. Select the eighth-pass model only; no checkpoint or epoch-count selection from holdout/development outcomes.',
        resources='No new stochastic collection. Reuse the 2304 audited third-batch continuations, fit only its 1536 fit suffixes. Eight passes replace two for that final batch; the first two earlier E36 updates stay in the starting actor. Then 256 greedy late diagnostics and the unchanged 1024 natural-start development gate.',
        verification='Verify inherited E36 completion, all copied label evidence, actor/data identities and the exact two-pass parameter hash. Independently replay all final diagnostics and development terminals; fresh NN/MCTS winner reruns and public-state NN/key/doubleboss/Act4 audits. Faults are not losses.',
        limits='Additional optimizer exposure to the E36 final on-policy batch; not a new collection or a comparison of data size. Label holdout is not unseen acceptance. The result cannot rule out other policy-gradient schedules. Original Java parity INCOMPLETE; Prismatic Shard excluded.')
    plan['training'].update(epochs=8, seed=old_plan['training']['seed'] + 2,
        record_state_hash_at_epochs=[2, 8], expected_state_hashes={'2': checkpoint['state_hash']})
    plan['control_two_pass_state_hash'] = checkpoint['state_hash']
    plan['control_checkpoint_sha256'] = training['checkpoint_sha256']
    plan['earlier_optimizer_updates'] = sum(i['optimizer_updates'] for i in training['iterations'][:2])
    H.write_json(root / 'plan.json', plan)
    H.write_json(root / 'source-evidence.json', evidence)
    E.freeze(root)
    print({'status': 'prepared', 'experiment': 'E37', 'epochs': 8, 'new_labels': 0,
        'control_two_pass_state_hash': checkpoint['state_hash']}, flush=True)


def source_contract(root):
    S.verify_files(root)
    L.verify_runtime(root)
    plan = H.read_json(root / 'plan.json')
    source = Path(plan['source'])
    for name, key in (('decision.json', 'source_decision_sha256'),
                      ('completion-verification.json', 'source_completion_sha256'),
                      ('training-report.json', 'source_training_sha256'),
                      ('update-magnitude-diagnostics.json', 'source_update_diagnostics_sha256')):
        assert S.sha(source / name) == plan[key]
    for item in H.read_json(root / 'source-evidence.json'):
        assert S.sha(item['source']) == S.sha(root / item['copied_path']) == item['sha256']
    ip = H.read_json(root / 'iterations/0/plan.json')
    assert ip['iteration'] == plan['source_iteration'] == 2
    assert S.sha(ip['actor']) == ip['actor_sha256']
    control = H.torch.load(source / 'candidate.pt', map_location='cpu', weights_only=True)
    assert S.sha(source / 'candidate.pt') == plan['control_checkpoint_sha256']
    assert H.state_hash(H.load_scorer(control)) == plan['control_two_pass_state_hash']
    assert plan['training']['seed'] == H.read_json(source / 'plan.json')['training']['seed'] + ip['iteration']
    return plan


def train(root):
    plan = source_contract(root)
    U.train(root, 0)
    dst = root / 'iterations/0'
    result = H.read_json(dst / 'training-report.json')
    prefix = next(h for h in result['history'] if h['epoch'] == 2)
    assert prefix['state_hash'] == plan['control_two_pass_state_hash']
    assert result['passes_per_decision'] == 8 and result['label_holdout_decisions_used'] == 0
    assert result['actor_sha256'] == H.read_json(dst / 'plan.json')['actor_sha256']
    assert S.sha(dst / 'candidate.pt') == result['checkpoint_sha256']
    shutil.copy2(dst / 'candidate.pt', root / 'candidate.pt')
    item = {'iteration': 0, 'source_iteration': 2, 'optimizer_updates': result['optimizer_updates'],
        'hashes': {n: S.sha(dst / n) for n in ('plan.json', 'candidate.pt', 'collection-report.json',
            'results-index.json', 'label-verification.json', 'training-report.json')}}
    H.write_json(root / 'training-report.json', {'status': 'complete', 'iterations': [item],
        'optimizer_updates': result['optimizer_updates'], 'earlier_optimizer_updates': plan['earlier_optimizer_updates'],
        'cumulative_optimizer_updates': result['optimizer_updates'] + plan['earlier_optimizer_updates'],
        'checkpoint_sha256': result['checkpoint_sha256'], 'label_holdout_decisions_used': 0,
        'final_model_selection': 'Exactly the eighth complete pass of the fixed final E36 collection; first two passes reproduce E36.'})
    H.write_json(root / 'optimizer-prefix-verification.json', {'status': 'complete', 'matched_epoch': 2,
        'state_hash': prefix['state_hash'], 'matched_updates': prefix['optimizer_updates'],
        'final_updates': result['optimizer_updates'], 'new_labels': 0,
        'training_report_sha256': S.sha(root / 'training-report.json')})
    print(H.read_json(root / 'training-report.json'), flush=True)


def verify(root):
    plan = source_contract(root)
    prefix = H.read_json(root / 'optimizer-prefix-verification.json')
    training = H.read_json(root / 'training-report.json')
    assert prefix['status'] == 'complete' and prefix['state_hash'] == plan['control_two_pass_state_hash']
    assert prefix['training_report_sha256'] == S.sha(root / 'training-report.json')
    assert prefix['final_updates'] == training['optimizer_updates']
    V.evaluation(root)
    source = Path(plan['source'])
    old_proof = H.read_json(source / 'completion-verification.json')
    for name, sha in old_proof['hashes'].items():
        assert S.sha(source / name) == sha
    old_index, new_index = (H.read_json(p / 'evaluation-index.json') for p in (source, root))
    old_hashes = {e['seed']: e['sha256'] for e in old_index}
    assert len(old_index) == len(new_index) == 1024
    assert set(old_hashes) == {e['seed'] for e in new_index}
    pairs, sims = Counter(), Counter()
    for e in new_index:
        old_path = source / f'evaluation/{e["seed"]}.json.gz'
        new_path = root / f'evaluation/{e["seed"]}.json.gz'
        assert S.sha(old_path) == old_hashes[e['seed']] and S.sha(new_path) == e['sha256']
        old, new = H.read_json(old_path), H.read_json(new_path)
        assert old['model_shas']['candidate'] == plan['control_checkpoint_sha256']
        assert new['model_shas']['candidate'] == training['checkpoint_sha256']
        a, b = old['status'] == 'heart_win', new['status'] == 'heart_win'
        pairs['both_win' if a and b else 'two_pass_only' if a else 'eight_pass_only' if b else 'both_fail'] += 1
        sims.update(two_pass=old['simulations'], eight_pass=new['simulations'])
    old_report, new_report = (H.read_json(p / 'report.json') for p in (source, root))
    assert pairs['both_win'] + pairs['two_pass_only'] == old_report['candidate_wins']
    assert pairs['both_win'] + pairs['eight_pass_only'] == new_report['candidate_wins']
    assert sims['two_pass'] == old_report['simulations'] and sims['eight_pass'] == new_report['simulations']
    H.write_json(root / 'exposure-comparison.json', {'status': 'complete', 'seeds': 1024,
        'two_pass_wins': old_report['candidate_wins'], 'eight_pass_wins': new_report['candidate_wins'],
        'paired': pairs, 'paired_exact_p': E.D.exact_p(pairs['two_pass_only'], pairs['eight_pass_only']),
        'simulations': sims, 'two_pass_report_sha256': S.sha(source / 'report.json'),
        'eight_pass_report_sha256': S.sha(root / 'report.json'),
        'limits': 'Paired training-development exposure comparison, not unseen acceptance or a checkpoint-selection criterion.'})
    proof = H.read_json(root / 'completion-verification.json')
    proof['optimizer_prefix_verified'] = True
    proof['hashes'].update({n: S.sha(root / n) for n in ('source-evidence.json', 'optimizer-prefix-verification.json', 'exposure-comparison.json')})
    proof['exposure_auditor_sha256'] = S.sha(__file__)
    H.write_json(root / 'completion-verification.json', proof)


def finish(root):
    S.verify_files(root)
    assert not (root / 'decision.json').exists()
    proof, report, plan = (H.read_json(root / p) for p in ('completion-verification.json', 'report.json', 'plan.json'))
    assert proof['status'] == 'complete' and proof['optimizer_prefix_verified']
    for name, sha in proof['hashes'].items():
        assert S.sha(root / name) == sha
    passed = proof['development_gate_passed']
    comparison = H.read_json(root / 'exposure-comparison.json')
    result = {'experiment': 'E37', 'status': 'complete', 'finished_at': P.utc(),
        'baseline_wins': report['baseline_wins'], 'candidate_wins': report['candidate_wins'],
        'paired': report['paired'], 'development_gate_passed': passed,
        'two_vs_eight_pass': comparison,
        'selected_for_fresh_acceptance': root.name if passed else None, 'new_acceptance_seeds': 0,
        'promoted_deployed_policy': False, 'candidate_sha256': S.sha(root / 'candidate.pt'),
        'report_sha256': S.sha(root / 'report.json'), 'verification_sha256': S.sha(root / 'completion-verification.json'),
        'limits': plan['limits']}
    H.write_json(root / 'decision.json', result)
    (root / '完整续局更新次数结果.md').write_text(
        '# E37：增加最后一批完整续局的训练遍数\n\n'
        '前两轮更新保留。最后一批由每条两遍改为八遍；前两遍全部权重与 E36 一致。'
        '没有新增标签、调整模型结构、挑选中间权重或更改整局开发门槛。\n\n'
        f'同一 1,024 个自然开局：原模型 {report["baseline_wins"]} 胜，候选 {report["candidate_wins"]} 胜。'
        f'配对结果：{report["paired"]}。开发门槛通过：{passed}。\n\n'
        f'与同一批次两遍更新的 E36 对照：{comparison["two_pass_wins"]}→{comparison["eight_pass_wins"]} 胜，'
        f'配对 {comparison["paired"]}，p={comparison["paired_exact_p"]}。\n\n'
        '终局、获胜新规划和路线／NN 核验见 completion-verification.json。'
        '这是历史训练开发结果，不是未见种子成绩；原版 Java 一致性 INCOMPLETE。\n')
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'train', 'diagnose', 'evaluate', 'verify', 'finish'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'prepare':
        prepare(root, args.source.resolve())
    elif args.command == 'diagnose':
        U.diagnose(root)
    elif args.command == 'evaluate':
        assert not (root / 'report.json').exists()
        L.evaluate(root)
    else:
        globals()[args.command](root)
