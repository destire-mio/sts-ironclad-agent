#!/usr/bin/env python3
"""Log natural pre-battle states without changing the frozen planner or NN."""
import argparse
from pathlib import Path
import time

import heart_branch_training as T

P, H, R, S = T.P, T.H, T.R, T.S


def run(runtime, seed, output, episode_seconds):
    S.verify_files(runtime)
    H.torch.set_num_threads(1)
    config = H.read_json(runtime / 'config.json')
    assert S.sha(R.sts.__file__) == S.sha(runtime / 'engine/slaythespire.cpython-312-darwin.so')
    output.mkdir(parents=True, exist_ok=False)
    H.write_json(output / 'inputs.json', {'seed': seed, 'runtime': str(runtime),
        'engine_sha256': S.sha(R.sts.__file__), 'model_sha256': S.sha(runtime / 'model.pt'),
        'episode_seconds': episode_seconds, 'scope': 'Separate diagnostic only, never overwrite a previous timeout or count it as a fresh acceptance result.'})
    H.write_json(output / 'seeds.json', {'diagnostic': [seed]})
    config = dict(config, episode_seconds=episode_seconds)
    checkpoint = H.torch.load(runtime / 'model.pt', map_location='cpu', weights_only=True)
    base = H.load_scorer(checkpoint)
    prefix, started = [], time.monotonic()
    class Logger:
        def choose(self, gc, observation, actions, descriptors):
            choice = base.choose(gc, observation, actions, descriptors)
            prefix.append({'kind': 'outside', 'before': R.fingerprint(gc), 'action': int(actions[choice].bits)})
            return choice
    native = R.sts.resolve_battle_recorded
    def logged_battle(gc, simulations, multiplier):
        before = R.fingerprint(gc)
        event = {'seed': seed, 'act': gc.act, 'floor': gc.floor_num, 'encounter': gc.encounter.name,
            'hp': gc.cur_hp, 'max_hp': gc.max_hp, 'prefix_length': len(prefix), 'fingerprint': before,
            'elapsed_seconds': time.monotonic() - started,
            'deck': [[c.id.name, c.upgrade_count, c.misc] for c in gc.deck]}
        H.write_json(output / 'before-battle-prefix.json.gz', prefix)
        H.write_json(output / 'progress.json', event)
        print({k: v for k, v in event.items() if k != 'deck'}, flush=True)
        result = dict(native(gc, simulations, multiplier))
        prefix.append({'kind': 'battle', 'before': before, **result})
        H.write_json(output / 'completed-prefix.json.gz', prefix)
        return result
    R.sts.resolve_battle_recorded = logged_battle
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, seed, 20)
    try:
        row = R.rollout(seed, config, gc=gc, net=Logger(), record=True, record_samples=False)
    finally:
        R.sts.resolve_battle_recorded = native
    assert row['prefix'] == prefix
    R.clock_input(gc, config)
    row.update(terminal_fingerprint=R.fingerprint(gc), engine_sha256=S.sha(R.sts.__file__),
        checkpoint_sha256=S.sha(runtime / 'model.pt'), replay_verified=False, terminal_state_verified=False)
    if R.target(row['status']) is not None:
        P.verify_terminal(R.replay(seed, row['prefix'], config), row)
        row.update(replay_verified=True, terminal_state_verified=True)
    H.write_json(output / 'episode.json.gz', row)
    print({k: row[k] for k in ('seed', 'status', 'floor', 'hp', 'simulations', 'seconds', 'replay_verified')}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime', type=Path, required=True)
    p.add_argument('--seed', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--episode-seconds', type=int, default=300)
    a = p.parse_args()
    run(a.runtime.resolve(), a.seed, a.output.resolve(), a.episode_seconds)
