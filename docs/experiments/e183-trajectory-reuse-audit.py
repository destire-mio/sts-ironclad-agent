"""Count independent families behind E183's reusable complete trajectories."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


def main(root):
    sys.path.insert(0, str(root/'program'))
    import heart_whole_policy_search as L
    E = L.E; plan = L.registered(root); E.proof(root/'search', 'completion.json')
    review = E.read(root/'result-review.json'); assert review['status'] == 'complete_reviewed'
    assert review['completion_sha256'] == E.sha(root/'search/completion.json')
    roles = E.read(root/'roles-private.json')
    refs = E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'), 'seed', 'reference')
    variants = {s: {} for s in roles['fit']}; hashes = {}

    def admit(path, sampled):
        run = E.read(path); seed = run['seed']; assert seed in variants and not run.get('error')
        assert run['status'] in ('heart_win', 'death', 'act3_without_heart')
        key = hashlib.sha256(json.dumps(run['prefix'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        hashes[str(path)] = E.sha(path)
        row = variants[seed].setdefault(key, dict(status=run['status'], path=str(path), copies=0))
        assert row['status'] == run['status']; row['copies'] += sampled
        return seed, key

    files = sorted((root/'search').glob('round-*/direction-*/*.json.gz')); assert len(files) == 768
    for path in files: admit(path, 1)
    reobserved = 0
    for seed in roles['fit']:
        assert sum(row['copies'] for row in variants[seed].values()) == 6
        path = Path(refs[seed]['path']); assert E.sha(path) == refs[seed]['sha256']
        n = len(variants[seed]); admit(path, 0); reobserved += len(variants[seed]) == n
    summary = Counter(); details = []; folds = {f: Counter() for f in range(3)}
    for seed, paths in variants.items():
        wins = sum(r['status'] == 'heart_win' for r in paths.values()); losses = len(paths)-wins
        values = dict(families=1, unique_paths=len(paths), parent_wins=int(refs[seed]['status'] == 'heart_win'),
            any_winner=int(wins > 0), mixed_outcomes=int(wins > 0 and losses > 0),
            winning_paths=wins, losing_paths=losses, win_lose_pairs=wins*losses,
            all_fail=int(wins == 0), all_win=int(losses == 0))
        summary.update(values)
        fold = int(hashlib.sha256(f'E73-family-fold:{seed}'.encode()).hexdigest(), 16) % 3
        folds[fold].update(values)
        details.append(dict(seed=seed, fold=fold, variants=list(paths.values())))
    assert summary['families'] == 128
    out = root/'trajectory-reuse-audit'; out.mkdir()
    E.write(out/'sources-private.json', dict(hashes=hashes)); E.write(out/'families-private.json', details)
    result = dict(status='complete_reviewed', summary=dict(summary), by_fold={str(f): dict(v) for f, v in folds.items()},
        sampled_games=768, parent_reobserved=reobserved, new_games=0, optimizer_updates=0,
        source_review_sha256=E.sha(root/'result-review.json'), source_completion_sha256=E.sha(root/'search/completion.json'),
        inputs_sha256=E.sha(out/'sources-private.json'), families_sha256=E.sha(out/'families-private.json'),
        runner_sha256=E.sha(__file__),
        limits=['Pair count is not independent-family count.', 'Any-winner count is a measured hindsight scope, not a deployable or global bound.',
                'E183 evaluation roles are excluded. This read-only audit does not authorize sampling expansion or rerunning the failed E41/E42 preference recipe.'])
    E.write(out/'report.json', result); print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--study', required=True, type=Path)
    main(parser.parse_args().study.resolve())
