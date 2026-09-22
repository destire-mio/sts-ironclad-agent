"""Use recorded native states to check scope and two route calculations."""
import argparse
from pathlib import Path
import sys


def main(root):
    sys.path.insert(0,str(root/'program'))
    import heart_route_prior_pilot as P
    E = P.E; plan = P.registered(root); x = P.C.D.runtime(plan['runtime'])
    refs = E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'),'seed','reference')
    families = E.read(root/'families-private.json')[:8]
    parent = E.parent_model(x); zero = P.RoutePolicy(x,0.); changed = P.RoutePolicy(x,3.5)
    decisions = maps = interventions = steps = 0; nonmap = 0; key_cases = 0; maximum_error = 0.
    for seed in families:
        ref = refs[seed]; assert E.sha(ref['path']) == ref['sha256']; run = E.read(ref['path'])
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,seed,20)
        for step in run['prefix']:
            x.R.clock_input(gc,x.config); before=x.R.fingerprint(gc); assert before == step['before']
            if step['kind'] == 'outside':
                actions = list(x.R.sts.get_legal_game_actions(gc)); _,ds,_ = x.A.build_choices(gc); obs=x.A.obs_vec(gc)
                with x.H.torch.no_grad():
                    baseline = parent.choose(gc,obs,actions,ds)
                    original = zero.choose(gc,obs,actions,ds)
                    candidate = changed.choose(gc,obs,actions,ds)
                    independent,_ = P.independent_choice(changed,gc,obs,actions,ds)
                assert original == baseline and actions[baseline].bits == step['action']
                assert candidate == independent and actions[candidate].is_valid(gc)
                assert x.R.fingerprint(gc) == before
                if x.R.kind(ds[baseline]) == x.A.AK_MAP:
                    maps += 1
                    for bonus in (0.,3.5):
                        recursive=P.route_scores(x,gc,actions,ds,bonus)
                        bottom_up=P.independent_route_scores(x,gc,actions,ds,bonus)
                        assert recursive.keys() == bottom_up.keys()
                        error=max(abs(recursive[i]-bottom_up[i]) for i in recursive)
                        maximum_error=max(maximum_error,error); assert error < 1e-10
                    teacher=x.R.heuristic_choice(gc,actions,ds)
                    if x.R.kind(ds[teacher]) == x.A.AK_MAP:
                        zero_scores=P.route_scores(x,gc,actions,ds,0.)
                        assert max(zero_scores,key=zero_scores.get)==teacher
                    if not gc.green_key and ds[baseline][x.A.OFF_BURNING_REACHABLE]:
                        assert ds[candidate][x.A.OFF_BURNING_REACHABLE]
                        key_cases += 1
                else:
                    assert candidate == baseline; nonmap += 1
                if candidate != baseline:
                    assert x.R.kind(ds[candidate]) == x.A.AK_MAP; interventions += 1
                decisions += 1
            x.R.replay_step(gc,step,x.config); steps += 1
        x.R.clock_input(gc,x.config); x.P.verify_terminal(gc,run)
    assert interventions > 0 and key_cases > 0 and nonmap > 0
    E.write(root/'preflight.json',dict(status='passed',families=8,recorded_steps=steps,decisions=decisions,
        mapped_decisions=maps,nonmap_parent_controls=nonmap,changed_map_choices=interventions,
        green_key_route_cases=key_cases,independent_map_score_max_error=maximum_error,
        zero_bonus_matches_frozen_parent=True,source_heuristic_matches_zero_route_scores=True,
        scoring_state_rng_unchanged=True,new_games=0,optimizer_updates=0,
        registration_sha256=E.sha(root/'registration.json'),runner_sha256=E.sha(__file__)))
    print(E.read(root/'preflight.json'),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    main(parser.parse_args().study.resolve())
