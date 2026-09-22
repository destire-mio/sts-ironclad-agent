"""Reconstruct natural battle exposure/failures from the1536 admitted old families.

Recorded actions only: no MCTS, new branch, optimizer or candidate evaluation.
Every source hash, state/RNG and terminal is checked while restoring the trace.
"""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import sys


def main(previous, output):
    sys.path.insert(0, str(previous / 'program'))
    import heart_late_campfire as L
    E = L.E
    plan = L.registered(previous)
    source = Path(plan['natural_source'])
    references = E.read(source / 'fit-references.json')
    roles = E.read(source / 'fit-roles.json')
    assert [r['seed'] for r in references] == roles and len(roles) == 1536
    x = L.C.D.runtime(plan['runtime'])
    output.mkdir()
    E.write(output / 'registration.json', dict(experiment='E163', source=str(source),
        references_sha256=E.sha(source / 'fit-references.json'), runtime_identity=x.identity,
        runner_sha256=E.sha(__file__), source_review_sha256=E.sha(previous / 'result-review.json'),
        scope='All1536 old natural parent traces, excluding forced alternatives. Restore every recorded action and battle; report exposure denominators and pre-battle public resources. No inference that a lost recorded fight was unwinnable.',
        new_games=0, optimizer_updates=0))
    episodes, battles = [], []
    for number, reference in enumerate(references):
        assert E.sha(reference['path']) == reference['sha256']
        run = E.read(reference['path'])
        assert run['seed'] == reference['seed'] and run['status'] == reference['status'] and not run.get('error')
        assert run['checkpoint_sha256'] == x.identity['model_sha256'] and run['engine_sha256'] == x.identity['engine_sha256']
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
        visited = set()
        last_battle = None
        for index, step in enumerate(run['prefix']):
            x.R.clock_input(gc, x.config)
            assert x.R.fingerprint(gc) == step['before']
            visited.add(gc.act)
            if step['kind'] == 'battle':
                before = dict(seed=run['seed'], prefix_index=index, act=gc.act, floor=gc.floor_num,
                    room=gc.cur_room.name, encounter=gc.encounter.name, hp_before=gc.cur_hp,
                    max_hp_before=gc.max_hp, deck_size=len(gc.deck), relic_count=len(gc.relics),
                    actions=len(step['actions']), simulations=step['simulations'], turns=step['turns'], outcome=step['outcome'])
            x.R.replay_step(gc, step, x.config)
            if step['kind'] == 'battle':
                before.update(hp_after=gc.cur_hp, max_hp_after=gc.max_hp,
                    terminal_status_after=x.R.terminal(gc), hp_loss=before['hp_before']-gc.cur_hp)
                battles.append(before)
                last_battle = before
        x.R.clock_input(gc, x.config)
        x.P.verify_terminal(gc, run)
        episodes.append(dict(seed=run['seed'], status=run['status'], act=run['act'], floor=run['floor'],
            reached_acts=sorted(visited), keys=run['keys'], last_battle=last_battle,
            last_step_kind=run['prefix'][-1]['kind']))
        if (number + 1) % 256 == 0:
            print(dict(families=number+1, battles=len(battles)), flush=True)
    E.write(output / 'episodes-private.json', episodes)
    E.write(output / 'battles-private.json', battles)
    deaths = [r for r in episodes if r['status'] == 'death']
    by_act = []
    for act in range(1, 5):
        seen = [r for r in episodes if act in r['reached_acts']]
        lost = [r for r in deaths if r['act'] == act]
        fight = [b for b in battles if b['act'] == act]
        by_act.append(dict(act=act, natural_families_reaching=len(seen), deaths=len(lost),
            observed_battles=len(fight), observed_survived_battles=sum(b['hp_after'] > 0 for b in fight)))
    exposure = Counter(b['encounter'] for b in battles)
    lost = Counter(r['last_battle']['encounter'] for r in deaths if r['last_step_kind'] == 'battle')
    encounters = [dict(encounter=name, observed_battles=exposure[name], natural_deaths=count)
                  for name, count in lost.most_common()]
    hp = Counter()
    for row in deaths:
        if row['last_step_kind'] != 'battle':
            hp['nonbattle_death'] += 1
            continue
        battle = row['last_battle']
        fraction = battle['hp_before'] / battle['max_hp_before']
        hp['<=25%' if fraction <= .25 else '25-50%' if fraction <= .5 else '50-75%' if fraction <= .75 else '>75%'] += 1
    result = dict(status='complete', experiment='E163', families=len(episodes), battles=len(battles),
        terminal_statuses=dict(Counter(r['status'] for r in episodes)), by_act=by_act,
        fatal_encounters=encounters, pre_fatal_battle_hp_buckets=dict(hp),
        recorded_battle_hp_changes=dict(negative=sum(b['hp_loss']<0 for b in battles), zero=sum(b['hp_loss']==0 for b in battles), positive=sum(b['hp_loss']>0 for b in battles)),
        new_games=0, MCTS_calls=0, optimizer_updates=0,
        limits='Observed parent trajectories on historical fit families, not causal attribution or a proof that MCTS could not win. Battle HP change includes the recorded combat settlement. Repeated encounters within a family are exposures, not independent families.')
    E.write(output / 'report.json', result)
    E.write(output / 'completion.json', dict(status='complete', hashes={p.name:E.sha(p) for p in output.iterdir() if p.is_file()}))
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.previous.resolve(), args.output.resolve())
