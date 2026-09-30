"""Re-encode audited fixed-parent card continuations, without new searches.

Rows pair the public state BEFORE a recorded card decision with that chosen
card and its fixed-parent Heart outcome. Nothing before the forced first card
is labelled with the outcome of a later intervention.
"""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import time
import traceback

import heart_early_card_scope as E

VERSION = 'public_card_value_v1'


@lru_cache(maxsize=1)
def runtime(path):
    return E.load_runtime(path)


def feature_spec(x):
    A = x.A
    tail = A.BASE_OBS_DIM - (6*A.CARD_CAP + 32 + 2*A.RELIC_CAP + 5*A.POTION_CAP)
    # Public scalars, keys/rooms/screen/current boss, visible map, inventory,
    # special card values, relic counters, potions and public flame position.
    # Drop event scratch storage and internal reward/encounter probabilities.
    observations = list(range(13)) + list(range(32, 75)) + list(range(tail-805, A.OBS_DIM))
    descriptors = [A.AK_REWARD_CARD, A.AK_REWARD_SKIP, A.AK_REWARD_SINGING_BOWL]
    descriptors += list(range(A.OFF_CARD, A.OFF_CARD_MISC+1))
    E.require(tail > 880 and set(A._maxes[tail:tail+2*A.CARD_CAP]) == {20.},
              'unexpected public observation layout')
    return dict(version=VERSION, observation_dim=A.OBS_DIM, descriptor_dim=A.DESC_DIM,
                observations=observations, descriptors=descriptors,
                width=len(observations)+len(descriptors), deck_offset=tail,
                limits='No seed, RNG, prefix index, terminal status, event scratch or hidden probabilities in features. Card IDs carry no hand-written values.')


def features(observation, descriptor, spec):
    E.require(len(observation) == spec['observation_dim'] and
              len(descriptor) == spec['descriptor_dim'], 'feature dimensions differ')
    values = [observation[i] for i in spec['observations']]
    values += [descriptor[i] for i in spec['descriptors']]
    E.require(len(values) == spec['width'], 'feature width differs')
    return values


def admitted_nodes(nodes, roles):
    E.require(len(roles) == len(set(roles)), 'duplicate fit role')
    E.require([n['seed'] for n in nodes] == roles, 'fit order or coverage differs')
    for node in nodes:
        state = node['state']
        E.require(node['split'] == state['split'] == 'fit' and
                  node['seed'] == state['seed'], 'non-fit or cross-family input')
        leaves = E.indexed(node['leaves'], 'candidate', 'first-card leaf')
        E.require(set(leaves) == set(state['candidates']) and state['chosen'] in leaves,
                  'incomplete first-card menu')
        for leaf in leaves.values():
            E.binary(leaf['target'])


def registered(root):
    registration = E.read(root/'registration.json')
    E.require(E.sha(__file__) == registration['runner_sha256'], 'data runner changed')
    for path, digest in registration['hashes'].items():
        E.require(E.sha(path) == digest, 'registered data input changed: '+path)
    plan = E.read(root/'protocol.json')
    E.require(plan['new_sampling_games'] == plan['MCTS_searches'] == 0, 'no new game budget')
    source = Path(plan['source'])
    proof = E.read(source/'result-review.json')
    E.require(proof['status'] == 'complete' and proof['all10240_leaf_hashes_and_audited_terminal_targets_match'],
              'first-card source audit not accepted')
    E.require(proof['completion_sha256'] == E.sha(source/'completion-verification.json'),
              'source audit completion changed')
    nodes, roles = E.read(root/'fit-nodes.json'), E.read(root/'fit-roles.json')
    admitted_nodes(nodes, roles)
    E.require(len(nodes) == 1536, 'original fit denominator changed')
    return plan, nodes, roles


def extract_family(x, node, per_act=8):
    E.require(node['split'] == node['state']['split'] == 'fit', 'fit-only extraction')
    state = node['state']; spec = feature_spec(x); branches = []; checked_steps = 0
    for leaf in node['leaves']:
        E.require(E.sha(leaf['path']) == leaf['sha256'], 'terminal source changed')
        run = E.read(leaf['path'])
        E.require(run['seed'] == node['seed'] and not run.get('error') and
                  run['status'] in ('heart_win', 'death', 'act3_without_heart') and
                  E.binary(run['target']) == int(run['status'] == 'heart_win') == leaf['target'],
                  'wrong terminal label')
        E.require(run['checkpoint_sha256'] == x.identity['model_sha256'] and
                  run['engine_sha256'] == x.identity['engine_sha256'], 'wrong continuation identity')
        E.require(run['prefix'][state['prefix_index']]['action'] == state['actions'][leaf['candidate']],
                  'wrong forced first card')
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, node['seed'], 20)
        root_row = None; later = defaultdict(list); opportunities = Counter()
        for i, step in enumerate(run['prefix']):
            x.R.clock_input(gc, x.config)
            E.require(x.R.fingerprint(gc) == step['before'], 'state/RNG replay differs')
            if i >= state['prefix_index'] and step['kind'] == 'outside' and \
                    gc.screen_state == x.R.sts.ScreenState.REWARDS and gc.rewards['cards']:
                actions = list(x.R.sts.get_legal_game_actions(gc))
                _, descriptors, _ = x.A.build_choices(gc)
                bits = [int(a.bits) for a in actions]; chosen = bits.index(step['action'])
                identity = x.J.card_option(descriptors[chosen])
                if identity is not None:
                    obs = x.A.obs_vec(gc)
                    before = x.R.fingerprint(gc)
                    vector = features(obs, descriptors[chosen], spec)
                    E.require(before == x.R.fingerprint(gc), 'feature extraction mutated state/RNG')
                    row = dict(prefix_index=i, act=gc.act, floor=gc.floor_num, card_id=identity,
                               action=int(actions[chosen].bits), features=x.R.sparse(vector))
                    if i == state['prefix_index']:
                        E.require(chosen == leaf['candidate'] and before == state['fingerprint'],
                                  'wrong first-card state or selection')
                        E.require(x.R.sparse(obs) == state['observation'] and
                                  [x.R.sparse(d) for d in descriptors] == state['descriptors'],
                                  'registered first-card encoding differs')
                        root_row = row
                    else:
                        act = int(gc.act); opportunities[act] += 1
                        row['selection_key'] = hashlib.sha256(f'{i}'.encode()).hexdigest()
                        later[act].append(row)
                        later[act].sort(key=lambda r: r['selection_key'])
                        later[act] = later[act][:per_act]
            x.R.replay_step(gc, step, x.config); checked_steps += 1
        x.R.clock_input(gc, x.config); x.P.verify_terminal(gc, run)
        E.require(root_row is not None, 'missing forced-root training row')
        branches.append(dict(candidate=leaf['candidate'], target=leaf['target'], root=root_row,
                             later={str(a): rows for a, rows in sorted(later.items())},
                             opportunities=dict(opportunities), source_sha256=leaf['sha256']))
    return dict(status='complete', seed=node['seed'], split='fit', branches=branches,
                checked_steps=checked_steps, terminal_replays=len(branches),
                state_rng_replay_verified=True, new_sampling_games=0, MCTS_searches=0,
                feature_spec_sha256=hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest())


def worker(job, config):
    try:
        x = runtime(job['runtime'])
        result = extract_family(x, job['node'], config['retained_per_act'])
    except Exception:
        result = dict(status='extraction_error', seed=job['seed'], error=traceback.format_exc())
    runtime(job['runtime']).H.write_json(Path(job['output']), result)


def extract(root):
    plan, nodes, roles = registered(root); x = runtime(plan['runtime'])
    spec = feature_spec(x)
    E.require(spec == E.read(root/'feature-spec.json'), 'public feature contract changed')
    jobs = [dict(mode='prefix', seed=n['seed'], node=n, runtime=plan['runtime'],
                 output=str(root/'families'/f'{n["seed"]}.json.gz')) for n in nodes]
    config = dict(x.config, workers=plan['workers'], retained_per_act=plan['retained_per_act'])
    deadline = time.monotonic()+plan['timeout_seconds']; all_rows = []
    for offset in range(0, len(jobs), 128):
        batch = jobs[offset:offset+128]
        results = x.H.run_jobs(root, batch, config, f'E140_reencode_{offset}', deadline, worker_fn=worker)
        E.require(len(results) == len(batch), 'missing family extraction')
        for job, row in zip(batch, results):
            E.require(row['status'] == 'complete' and row['seed'] == job['seed'],
                      'family extraction failed: '+str(row))
        all_rows.extend(results)
    E.require([r['seed'] for r in all_rows] == roles, 'missing or duplicate assigned family')
    later = sum(len(rows) for r in all_rows for b in r['branches'] for rows in b['later'].values())
    E.write(root/'completion-verification.json', dict(status='complete', zero_faults=True,
        families=len(all_rows), terminal_replays=sum(r['terminal_replays'] for r in all_rows),
        root_rows=sum(len(r['branches']) for r in all_rows), later_rows=later,
        replayed_steps=sum(r['checked_steps'] for r in all_rows), new_sampling_games=0,
        MCTS_searches=0, optimizer_updates=0, external_holdout_evaluations=0,
        hashes={j['output']: E.sha(j['output']) for j in jobs}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'extract'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args(); root = args.study.resolve()
    registered(root) if args.command == 'check' else extract(root)
