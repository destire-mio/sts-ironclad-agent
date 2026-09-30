"""Read original P200 artifacts and reconstruct budgets, ancestry and outcomes."""
import argparse
from collections import Counter
from pathlib import Path

import heart_early_card_scope as E


def require(value, message):
    if not value:
        raise ValueError(message)


def review(root):
    protocol = E.read(root / 'protocol.json'); recipe = protocol['recipe']
    references = E.read(root / 'references.json'); result = E.read(root / 'result.json')
    require(result['status'] == 'complete', 'incomplete study cannot pass review')
    require(len(references) == recipe['families'] == result['assigned'], 'wrong denominator')
    counts = Counter(); rows = []; hashes = {}
    for reference in references:
        seed = reference['seed']; folder = root / 'families' / str(seed)
        source = E.read(reference['path']); require(E.sha(reference['path']) == reference['sha256'], 'source changed')
        family = E.read(folder / 'result.json'); require(family['status'] == 'complete', 'family failed')
        records = {'parent': dict(run=source, changes=[])}
        listed = [name for stage in ('shared', 'single', 'composite') for name in family['groups'][stage]]
        require(len(listed) == len(set(listed)) == family['candidates'], 'duplicate/missing candidates')
        require(len(family['groups']['shared']) <= recipe['shared'] and
                all(len(family['groups'][stage]) <= recipe['extra'] for stage in ('single', 'composite')), 'budget exceeded')
        for name in listed:
            path = folder / (name + '.json.gz'); records[name] = E.read(path); hashes[str(path)] = E.sha(path)
        for name in listed:
            record = records[name]; parent = records[record['parent_id']]; changes = record['changes']; run = record['run']
            require(record['id'] == name and run['seed'] == seed and run['status'] in ('death', 'heart_win', 'act3_without_heart')
                    and not run.get('error'), 'invalid terminal')
            require(0 < len(changes) <= recipe['max_changes'], 'invalid intervention count')
            last = changes[-1]; index = last['index']
            require(run['prefix'][:index] == parent['run']['prefix'][:index], 'changed inherited prefix')
            require(run['prefix'][index] == dict(kind='outside', before=last['before'], action=last['action']), 'forced root differs')
            require(parent['run']['prefix'][index]['before'] == last['before'] and
                    parent['run']['prefix'][index]['action'] != last['action'], 'no actual root change')
            require(changes[:-1] == [c for c in parent['changes'] if c['index'] < index], 'intervention ancestry differs')
            if name.startswith(('single-', 'shared-')):
                require(record['parent_id'] == 'parent' and len(changes) == 1, 'single arm contains composition')
            else:
                require(not record['parent_id'].startswith('single-'), 'single-arm outcome leaked into composite search')
            for change in changes:
                require(run['prefix'][change['index']] == dict(kind='outside', before=change['before'], action=change['action']), 'lost earlier change')
            counts['candidates'] += 1; counts['candidate_simulations'] += run['simulations']
        selected = {}
        for stage in ('single', 'composite'):
            eligible = ['parent'] + family['groups']['shared'] + family['groups'][stage]
            wins = [name for name in eligible if records[name]['run']['status'] == 'heart_win']
            chosen = family['selected'][stage]
            require(chosen['id'] in eligible and chosen['win'] == bool(wins), 'teacher outcome selection differs')
            require(chosen['changes'] == records[chosen['id']]['changes'], 'selected changes differ')
            selected[stage] = bool(wins)
            counts[stage + '_wins'] += bool(wins)
        for name in set(family['selected'][stage]['id'] for stage in ('single', 'composite') if selected[stage]):
            path = folder / ('replan-' + name + '.json.gz'); rerun = E.read(path); original = records[name]['run']
            require(rerun['status'] == 'heart_win' and rerun['prefix'] == original['prefix'] and
                    rerun['terminal_fingerprint'] == original['terminal_fingerprint'], 'winner fresh plan differs')
            counts['winner_replans'] += 1; counts['replan_simulations'] += rerun['simulations']; hashes[str(path)] = E.sha(path)
        if family['fresh_control']:
            control = E.read(folder / 'parent-control.json.gz')
            require(control['prefix'] == source['prefix'] and control['terminal_fingerprint'] == source['terminal_fingerprint'], 'parent control differs')
            counts['parent_controls'] += 1; counts['control_simulations'] += control['simulations']
        counts['parent_wins'] += source['status'] == 'heart_win'
        rows.append(dict(seed=seed, single=selected['single'], composite=selected['composite'],
                         composite_changes=len(family['selected']['composite']['changes'])))
    require(counts['single_wins'] == result['single_teacher_wins'] and counts['composite_wins'] == result['composite_teacher_wins'], 'result summary differs')
    preflight = E.read(root / 'preflight.json')
    new_plans = counts['candidates'] + counts['winner_replans'] + counts['parent_controls'] + preflight['new_plans']
    require(new_plans <= protocol['total_new_plans_maximum'], 'total planning budget exceeded')
    report = dict(status='complete_artifact_review', counts=dict(counts), new_plans=new_plans, rows=rows,
                  result_sha256=E.sha(root / 'result.json'), hashes=hashes,
                  native_replay='Inherited from every production candidate check and selected fresh replans; this review reconstructs ancestry/budget from raw artifacts.',
                  limits='Teacher success is a best-found lower bound using terminal information, not public-policy performance; sampled single failures do not prove all single changes fail.')
    E.write(root / 'artifact-review.json', report)
    print({k:v for k,v in report.items() if k not in ('rows', 'hashes')})


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--root', required=True, type=Path)
    review(p.parse_args().root.resolve())
