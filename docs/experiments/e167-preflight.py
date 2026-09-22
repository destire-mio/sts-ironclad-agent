"""Validate all32 native roots and reject corrupt state before any new rollout."""
import argparse
import copy
import hashlib
from pathlib import Path
import sys


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_second_boss_pilot as L
    E = L.E
    plan = L.registered(root)
    E.proof(root, 'preparation.json')
    states = E.read(root / 'states-private.json')
    inventory = E.read(root / 'inventory-private.json')
    roles = E.read(Path(plan['natural_source']) / 'fit-roles.json')
    ordered = sorted(roles, key=lambda s: hashlib.sha256(f'E167-act2-boss-relic:{s}'.encode()).hexdigest())
    assert [r['seed'] for r in inventory] == ordered[:len(inventory)]
    assert [r['seed'] for r in states] == [r['seed'] for r in inventory if r['reason'] == 'eligible']
    assert len(states) == 32 and inventory[-1]['reason'] == 'eligible'
    x = L.C.D.runtime(plan['runtime'])
    parent = E.parent_model(x)
    checked = 0
    for state in states:
        assert E.sha(state['source_path']) == state['source_sha256']
        row = E.read(state['source_path'])
        gc = x.R.replay(state['seed'], row['prefix'][:state['prefix_index']], x.config)
        assert x.R.fingerprint(gc) == state['fingerprint']
        actions = list(x.R.sts.get_legal_game_actions(gc))
        _, descriptors, _ = x.A.build_choices(gc)
        observation = x.A.obs_vec(gc)
        chosen = parent.choose(gc, observation, actions, descriptors)
        assert L.candidates(x, gc, actions, descriptors, chosen) == state['candidates']
        assert chosen == state['chosen']
        assert [int(a.bits) for a in actions] == state['actions']
        assert x.R.sparse(observation) == state['observation']
        assert [x.R.sparse(d) for d in descriptors] == state['descriptors']
        checked += L.audit_parent_choices(x, row, state, chosen, parent)
    state = copy.deepcopy(states[0])
    state['fingerprint'] = 'corrupt-state-negative-control'
    rollout = x.R.rollout
    attempted = []
    def reject_rollout(*args, **kwargs):
        attempted.append(True)
        raise AssertionError('invalid root reached MCTS')
    x.R.rollout = reject_rollout
    try:
        try:
            x.P.execute_branch(E.read(state['source_path']), state, state['chosen'], x.config, parent)
        except ValueError as error:
            assert str(error) == 'root state or RNG changed'
        else:
            raise AssertionError('corrupt root admitted')
        assert not attempted
    finally:
        x.R.rollout = rollout
    assert all(s['act'] == 2 and s['screen'] == 'BOSS_RELIC_REWARDS' for s in states)
    assert sum(len(s['candidates']) for s in states) <= 128
    result = dict(status='passed', native_roots_verified=32, source_parent_choices_verified=checked,
        hash_order_and_scanned_inventory_verified=True, corrupt_root_rejected_before_rollout=True,
        new_games=0, optimizer_updates=0, runner_sha256=E.sha(L.__file__), reviewer_sha256=E.sha(__file__))
    E.write(root / 'preflight.json', result)
    print(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
