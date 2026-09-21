"""Independent small trees and rejected executions for the E131 pilot."""
import copy
import importlib.util
import json
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location('early_scope',
    Path(__file__).resolve().parents[1] / 'agent/heart_early_card_scope.py')
E = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E)


def tree(seed, targets, parent_choices=(0, 0)):
    """targets[c] is None for death before a boss, or two boss outcomes."""
    first = {'seed': seed, 'id': f'{seed}-card', 'prefix_index': 5, 'chosen': 0,
             'candidates': [0, 1], 'actions': [100, 50]}
    branches = []
    for card, values in enumerate(targets):
        second = None if values is None else {'seed': seed, 'prefix_index': 50 + card,
            'early_card_candidate': card, 'chosen': parent_choices[card], 'candidates': [0, 1],
            'actions': [11, 9], 'fingerprint': f'{seed}-boss-{card}'}
        branches.append({'card_candidate': card, 'parent_target': 0 if values is None else values[parent_choices[card]],
            'boss_root': second, 'leaves': [] if values is None else [
                {'candidate': i, 'target': y, 'path': f'{seed}-{card}-{i}', 'sha256': str(i)}
                for i, y in enumerate(values)], 'source_path': f'{seed}-{card}', 'source_sha256': str(card)})
    return {'seed': seed, 'card_root': first, 'branches': branches}


class ScopeOutcomesTest(unittest.TestCase):
    def fixture(self):
        # 1 dies before the card; 2 needs both changes; 3 needs the card;
        # 4 already wins; 5 is rescuable only under old scope; 6 changes the
        # parent's later relic choice because its new card changes the state.
        refs = [{'seed': i, 'target': int(i == 4), 'status': 'heart_win' if i == 4 else 'death',
                 'act': 1 if i in (1, 2, 3) else 4 if i == 4 else 2} for i in range(1, 7)]
        trees = [tree(2, [None, [0, 1]]), tree(3, [None, [1, 1]]),
                 tree(4, [[1, 0], [0, 0]]), tree(5, [[0, 0], [0, 0]]),
                 tree(6, [[0, 0], [0, 1]], parent_choices=(0, 1))]
        old = [{'seed': i, 'split': 'fit', 'parent': int(i == 4), 'joint_oracle': int(i in (4, 5))}
               for i in range(1, 7)]
        return refs, trees, old

    def test_family_denominator_and_known_branch_outcomes(self):
        report = E.summarize(*self.fixture())
        self.assertEqual(report['families'], 6)
        self.assertEqual(report['hindsight_counts'], {
            'parent': 1, 'card_only': 3, 'relic_only': 1, 'joint': 4, 'old_joint': 2})
        self.assertEqual(report['mixed_families'], 4)
        self.assertEqual(report['new_rescue_families'], 3)
        self.assertEqual(report['old_only_rescue_families'], 1)
        self.assertEqual(report['joint_only_rescue_families'], 1)
        self.assertEqual(report['rescued_original_act1_deaths'], 2)
        self.assertEqual(report['no_early_card_families'], 1)

    def test_later_parent_choice_is_local_to_changed_card_branch(self):
        refs, trees, _ = self.fixture()
        both = E.tree_outcome(refs[1], trees[0])
        changed_parent = E.tree_outcome(refs[5], trees[-1])
        self.assertEqual((both['card_only'], both['relic_only'], both['joint']), (0, 0, 1))
        self.assertTrue(both['joint_only_rescue'])
        self.assertEqual(changed_parent['card_only'], 1)
        self.assertFalse(changed_parent['joint_only_rescue'])

    def test_missing_duplicate_or_cross_branch_leaves_reject(self):
        def missing(t): t['branches'][1]['leaves'].pop()
        def duplicate(t): t['branches'].append(copy.deepcopy(t['branches'][1]))
        def wrong_family(t): t['branches'][1]['boss_root']['seed'] = 90
        def wrong_branch(t): t['branches'][1]['boss_root']['early_card_candidate'] = 0
        def backwards(t): t['branches'][1]['boss_root']['prefix_index'] = 3
        def bad_parent(t): t['branches'][1]['parent_target'] = 1
        def null_label(t): t['branches'][1]['leaves'][1]['target'] = None
        for change in (missing, duplicate, wrong_family, wrong_branch, backwards, bad_parent, null_label):
            with self.subTest(change=change.__name__):
                refs, trees, _ = self.fixture()
                change(trees[0])
                with self.assertRaises(ValueError):
                    E.tree_outcome(refs[1], trees[0])

    def test_wrong_reference_or_scope_family_rejects(self):
        refs, trees, old = self.fixture()
        with self.assertRaises(ValueError): E.summarize(refs + [refs[0]], trees, old)
        with self.assertRaises(ValueError): E.summarize(refs, trees, old[:-1])
        old[0]['split'] = 'label_holdout'
        with self.assertRaises(ValueError): E.summarize(refs, trees, old)

    def test_rescue_verification_is_required_before_data_expansion(self):
        report = E.summarize(*self.fixture())
        gate = {'complete_families': 6, 'minimum_mixed_B_families': 4,
                'minimum_B_winning_A_all_lose_families': 3}
        self.assertTrue(E.expansion_gate(report, gate, [2, 3, 6]))
        self.assertFalse(E.expansion_gate(report, {**gate, 'minimum_mixed_B_families': 5}, [2, 3, 6]))
        for bad in ([2, 3], [2, 3, 6, 6], [2, 3, 5]):
            with self.assertRaises(ValueError): E.expansion_gate(report, gate, bad)

    def test_winner_selection_uses_action_identity_order(self):
        value = tree(7, [[0, 1], [0, 1]])
        self.assertEqual(E.winning_trace(value)['path'], '7-1-1')
        value['branches'].reverse()
        for branch in value['branches']: branch['leaves'].reverse()
        self.assertEqual(E.winning_trace(value)['path'], '7-1-1')

    def test_assigned_families_are_invariant_to_input_order(self):
        roles = {'fit': list(range(4608)), 'label_holdout': list(range(4608, 5632)),
                 'train_development': list(range(5632, 6144))}
        selection = {'input_role': 'fit', 'selected_families': 128,
                     'namespace': 'e131-early-card-scope-20260921:'}
        first = E.selected_families(roles, selection)
        random.Random(11).shuffle(roles['fit'])
        self.assertEqual(E.selected_families(roles, selection), first)
        self.assertEqual(len(set(first)), 128)
        self.assertFalse(set(first) & set(roles['label_holdout'] + roles['train_development']))
        roles['fit'][0] = roles['label_holdout'][0]
        with self.assertRaises(ValueError): E.selected_families(roles, selection)

    def test_repeated_policy_queries_do_not_consume_the_intervention(self):
        runtime = SimpleNamespace(R=SimpleNamespace(fingerprint=lambda gc: gc.fingerprint))
        parent = SimpleNamespace(choose=lambda *args: 0)
        state = {'prefix_index': 5, 'fingerprint': 'a', 'actions': [11, 22], 'chosen': 0}
        policy = E.ForcedChoices(runtime, parent, [E.forced(state, 1)])
        actions = [SimpleNamespace(bits=11), SimpleNamespace(bits=22)]
        gc = SimpleNamespace(fingerprint='a')
        self.assertEqual(policy.choose(gc, [], actions, []), 1)
        self.assertEqual(policy.choose(gc, [], actions, []), 1)
        gc.fingerprint = 'later'
        self.assertEqual(policy.choose(gc, [], actions, []), 0)


class CompletedStudyGateTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.study = self.root / 'study'

    def put(self, relative, data):
        path = self.study / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return path

    def complete(self):
        worker = self.study / 'worker.py'
        worker.parent.mkdir(parents=True, exist_ok=True)
        worker.write_text('pass\n')
        self.put('training-execution-registration.json', {'hashes': {'worker.py': E.sha(worker)}})
        self.put('execution/started.json', {'input_proofs_sha256': {str(worker): E.sha(worker)}})
        jobs = []
        for name in ('fit', 'verify', 'finalize'):
            path = self.put(f'execution/{name}/pipeline-process-exit.json', {
                'exit_code': 0, 'cleanup': {'clean': True, 'remaining_members': []}})
            jobs.append({'name': name, 'exit_code': 0, 'process_exit_sha256': E.sha(path)})
        self.put('scale/development-decision.json', {'status': 'complete', 'selected_arm': None,
            'arms': {arm: {'passed': False, 'stage': 'label_holdout'} for arm in ('small', 'expanded')}})
        self.put('scale/learning-verification.json', {'status': 'complete', 'assigned_heldout_families': 1024,
            'arms': {arm: {'passed': False, 'live_choices_verified': True} for arm in ('small', 'expanded')}})
        completion = self.put('scale/development-completion.json', {'status': 'complete', 'selected_arm': None,
            'hashes': {name: E.sha(self.study / 'scale' / name)
                       for name in ('development-decision.json', 'learning-verification.json')}})
        self.put('training-execution.json', {'status': 'complete', 'evidence_scope': 'simulator_only',
            'selected_arm': None, 'jobs': jobs, 'development_completion_sha256': E.sha(completion),
            'registration_sha256': E.sha(self.study / 'training-execution-registration.json'),
            'execution_started_sha256': E.sha(self.study / 'execution/started.json')})

    def test_incomplete_study_cannot_create_a_pilot_or_import_runtime(self):
        plan = self.root / 'pilot/plan.json'
        with self.assertRaises(FileNotFoundError):
            E.prepare(self.root / 'repository', plan, self.study, self.root / 'review.json')
        self.assertFalse(plan.parent.exists())
        self.assertFalse((self.root / 'repository').exists())

    def test_complete_rejected_study_returns_bound_review_inputs(self):
        self.complete()
        self.assertEqual(set(E.completed_study(self.study)), {'training_execution_sha256',
                         'development_completion_sha256', 'development_decision_sha256'})

    def test_candidate_success_requires_a_different_next_decision(self):
        self.complete()
        path = self.study / 'training-execution.json'
        self.put('training-execution.json', {**E.read(path), 'selected_arm': 'expanded'})
        with self.assertRaisesRegex(ValueError, 'qualified a candidate'):
            E.completed_study(self.study)

    def test_faults_and_live_descendants_are_not_threshold_failures(self):
        self.complete()
        for code, clean, members in ((124, True, []), (0, False, [123]), (0, True, [123])):
            with self.subTest(code=code, clean=clean, members=members):
                path = self.put('execution/fit/pipeline-process-exit.json', {
                    'exit_code': code, 'cleanup': {'clean': clean, 'remaining_members': members}})
                execution = E.read(self.study / 'training-execution.json')
                execution['jobs'][0].update(exit_code=code, process_exit_sha256=E.sha(path))
                self.put('training-execution.json', execution)
                with self.assertRaisesRegex(ValueError, 'fault or live descendants'):
                    E.completed_study(self.study)

    def test_changed_verification_cannot_enter_new_sampling(self):
        self.complete()
        path = self.study / 'scale/learning-verification.json'
        data = E.read(path)
        data['assigned_heldout_families'] = 1023
        self.put('scale/learning-verification.json', data)
        with self.assertRaisesRegex(ValueError, 'proof input changed'):
            E.completed_study(self.study)

    def admission_fixture(self):
        self.complete()
        repo = self.root / 'repository'
        source = repo / 'runs/source/natural'
        collector = self.study.parent / 'heart-e121-simulator-joint-labels-20260920-01'

        def put(path, value):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
            return path

        roles = {'fit': list(range(4608)), 'label_holdout': list(range(4608, 5632)),
                 'train_development': list(range(5632, 6144))}
        roles_path = put(source / 'seeds.json', roles)
        selection = {'input_role': 'fit', 'selected_families': 128,
            'namespace': 'e131-early-card-scope-20260921:',
            'source': str(roles_path.relative_to(repo)), 'source_sha256': E.sha(roles_path),
            'selected_ids_file': 'runs/pilot/families.json'}
        families = put(repo / selection['selected_ids_file'], E.selected_families(roles, selection))
        selection['selected_ids_file_sha256'] = E.sha(families)
        identity = {'model_sha256': 'a' * 64, 'engine_sha256': 'b' * 64}
        put(source / 'identity.json', identity)
        put(collector / 'relic-source/identity.json', identity)
        source_proof = put(source / 'completion-verification.json', {'status': 'complete',
            'zero_faults': True, 'natural_terminals': 6144, 'hashes': {'seeds.json': E.sha(roles_path)}})
        proofs = {}
        for arm in ('relic-source', 'joint'):
            accounting = put(collector / arm / 'collection-accounting.json', {
                'faults': [], 'requested': 1, 'returned': 1})
            label = {'status': 'complete', 'hashes': {'collection-accounting.json': E.sha(accounting)}}
            if arm == 'joint': label['zero_faults'] = True
            proofs[arm] = put(collector / arm / 'label-verification.json', label)
        collector_proof = put(collector / 'completion-verification.json', {'status': 'complete',
            'hashes': {str(p.relative_to(collector)): E.sha(p) for p in proofs.values()}})
        started = self.put('execution/started.json', {'input_proofs_sha256': {
            str(path): E.sha(path) for path in (source_proof, collector_proof, *proofs.values())}})
        execution = E.read(self.study / 'training-execution.json')
        execution['execution_started_sha256'] = E.sha(started)
        self.put('training-execution.json', execution)
        design = repo / 'docs/design.md'
        design.parent.mkdir(parents=True)
        design.write_text('Metadata-only fixture; no actual episodes or models.\n')
        plan = put(repo / 'runs/pilot/plan.json', {'experiment': 'E131', 'status': 'prepared_not_started',
            'design': 'docs/design.md', 'design_sha256': E.sha(design), 'selection': selection,
            'identity': {'parent_model_sha256': identity['model_sha256'], 'engine_sha256': identity['engine_sha256']}})
        put(repo / 'docs/experiments/e128-followup-analysis-evidence.json', {'E131_plan_sha256': E.sha(plan)})
        review = put(repo / 'runs/pilot/review.json', {'decision': 'execute_registered_E131',
            'runner_sha256': E.sha(E.__file__), 'gates': {
                'training_execution_sha256': E.sha(self.study / 'training-execution.json'),
                'development_completion_sha256': E.sha(self.study / 'scale/development-completion.json'),
                'development_decision_sha256': E.sha(self.study / 'scale/development-decision.json'),
                'relic-source_labels_sha256': E.sha(proofs['relic-source']),
                'joint_labels_sha256': E.sha(proofs['joint']), 'plan_sha256': E.sha(plan),
                'source_completion_sha256': E.sha(source_proof),
                'collector_completion_sha256': E.sha(collector_proof)}})
        return repo, plan, review, source_proof

    def test_complete_metadata_admission_without_native_import_or_output(self):
        repo, plan, review, _ = self.admission_fixture()
        admitted = E.admission(repo, plan, self.study, review)
        self.assertEqual(len(admitted[1]), 128)
        self.assertEqual(admitted[-1], E.read(review)['gates'])
        self.assertFalse((plan.parent / 'execution').exists())

    def test_old_result_review_cannot_activate_a_new_implementation(self):
        repo, plan, review, _ = self.admission_fixture()
        value = E.read(review)
        value['runner_sha256'] = '0' * 64
        review.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'bind this implementation'):
            E.prepare(repo, plan, self.study, review)
        self.assertFalse((plan.parent / 'execution').exists())

    def test_completed_study_must_have_used_the_registered_data(self):
        repo, plan, review, source_proof = self.admission_fixture()
        alternate = self.root / 'other-source-proof.json'
        alternate.write_bytes(source_proof.read_bytes())
        started = E.read(self.study / 'execution/started.json')
        started['input_proofs_sha256'][str(alternate)] = started['input_proofs_sha256'].pop(str(source_proof))
        self.put('execution/started.json', started)
        execution = E.read(self.study / 'training-execution.json')
        execution['execution_started_sha256'] = E.sha(self.study / 'execution/started.json')
        self.put('training-execution.json', execution)
        with self.assertRaisesRegex(ValueError, 'different source or continuation labels'):
            E.prepare(repo, plan, self.study, review)
        self.assertFalse((plan.parent / 'execution').exists())

    def test_alias_of_the_same_proof_file_keeps_its_identity(self):
        repo, plan, review, source_proof = self.admission_fixture()
        alias = self.root / 'same-source-proof.json'
        alias.symlink_to(source_proof)
        started = E.read(self.study / 'execution/started.json')
        started['input_proofs_sha256'][str(alias)] = started['input_proofs_sha256'].pop(str(source_proof))
        self.put('execution/started.json', started)
        execution = E.read(self.study / 'training-execution.json')
        execution['execution_started_sha256'] = E.sha(self.study / 'execution/started.json')
        self.put('training-execution.json', execution)
        value = E.read(review)
        value['gates']['training_execution_sha256'] = E.sha(self.study / 'training-execution.json')
        review.write_text(json.dumps(value))
        self.assertEqual(len(E.admission(repo, plan, self.study, review)[1]), 128)


if __name__ == '__main__':
    unittest.main()
