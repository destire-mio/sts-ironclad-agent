"""Join accepted historical routes into observed noncombat control transitions.

This data is for control Bellman backups, not fixed-parent terminal regression.
An earlier action gets reward zero and its actual next state, even when a later
action was forced. State fingerprints are provenance/dedup keys, never inputs.
"""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import time
import traceback

import heart_continuous_data as C

E = C.E


def public_row(row):
    return {k: row[k] for k in ('observation', 'descriptors', 'actions', 'act', 'floor')}


class Graph:
    def __init__(self, seed):
        self.seed = seed
        self.states, self.edges, self.routes = [], [], []
        self.state_ids, self.edge_ids = {}, {}

    def state(self, fingerprint, row, parent):
        E.require(isinstance(fingerprint, str) and len(fingerprint) == 64, 'invalid state identity')
        E.require(len(row['actions']) == len(row['descriptors']) and
                  len(row['actions']) == len(set(row['actions'])) and
                  0 <= parent < len(row['actions']), 'invalid full menu or parent')
        value = dict(public_row(row), fingerprint=fingerprint, parent=parent)
        if fingerprint in self.state_ids:
            index = self.state_ids[fingerprint]
            E.require(self.states[index] == value, 'same full state has different public encoding/parent')
            return index
        index = len(self.states)
        self.state_ids[fingerprint] = index
        self.states.append(value)
        return index

    def route(self, source, raw):
        E.require(raw['seed'] == self.seed and E.binary(raw['target']) == source['target'],
                  'route from another family or terminal')
        steps = [(i, s) for i, s in enumerate(raw['prefix']) if s['kind'] == 'outside']
        E.require(steps, 'complete route has no noncombat decision')
        route_edges = []
        for at, (prefix_index, step) in enumerate(steps):
            state_id = self.state_ids[step['before']]
            state = self.states[state_id]
            E.require(step['action'] in state['actions'], 'recorded action absent from full menu')
            chosen = state['actions'].index(step['action'])
            last = at == len(steps)-1
            next_state = None if last else self.state_ids[steps[at+1][1]['before']]
            reward = source['target'] if last else 0
            key = (state_id, chosen, next_state, reward, last)
            if key not in self.edge_ids:
                self.edge_ids[key] = len(self.edges)
                self.edges.append(dict(state=state_id, action=chosen, next_state=next_state,
                                       reward=reward, done=last, occurrences=0))
            edge = self.edge_ids[key]
            self.edges[edge]['occurrences'] += 1
            route_edges.append([prefix_index, edge])
        self.routes.append(dict(source, edges=route_edges, raw_steps=len(raw['prefix']),
                                terminal_fingerprint=raw['terminal_fingerprint']))

    def finish(self, counts):
        # Keep independently verified variants; do not average distinct successor
        # states away or duplicate shared prefixes as independent training rows.
        alternatives = defaultdict(set)
        for e in self.edges:
            alternatives[(e['state'], e['action'])].add((e['next_state'], e['reward'], e['done']))
        return dict(status='complete', split='fit', seed=self.seed, states=self.states,
            edges=self.edges, routes=self.routes, counts=dict(counts),
            multiple_successor_state_actions=sum(len(v)>1 for v in alternatives.values()))


def sources_for(node, tree, states, labels):
    C.D.admitted_nodes([node], [node['seed']])
    sources = []

    def add(scope, path, digest, target, forced):
        for s, candidate in forced:
            E.require(s['split'] == 'fit' and s['seed'] == node['seed'] and
                      candidate in s['candidates'], 'cross-family or non-fit forced state')
        sources.append(dict(scope=scope, path=path, sha256=digest, target=E.binary(target),
            forced=[dict(fingerprint=s['fingerprint'], prefix_index=s['prefix_index'],
                         action=s['actions'][candidate], parent=s['chosen'], actions=s['actions'],
                         descriptors=s['descriptors']) for s,candidate in forced]))

    for leaf in node['leaves']:
        add('first_card', leaf['path'], leaf['sha256'], leaf['target'], [(node['state'],leaf['candidate'])])
    if tree is not None:
        boss = tree['boss_root']
        E.require(tree['seed'] == node['seed'], 'wrong boss tree family')
        for branch in tree['branches']:
            forced = [(boss, branch['relic_candidate'])]
            add('boss', branch['source_path'], branch['source_sha256'], branch['parent_target'], forced)
            if branch['card_root'] is not None:
                state = states[branch['card_root']]
                E.require(state['relic_candidate'] == branch['relic_candidate'] and
                          state['source_sha256'] == branch['source_sha256'], 'card from a different boss branch')
                for leaf in labels[state['id']]:
                    add('conditional_card', leaf['path'], leaf['sha256'], leaf['target'],
                        forced+[(state, leaf['candidate'])])
    E.require(len({s['path'] for s in sources}) == len(sources), 'duplicate raw source assignment')
    return sources


def validate_raw(raw, source, seed, identity):
    E.require(raw['seed'] == seed and not raw.get('error') and
              raw['status'] in ('heart_win','death','act3_without_heart') and
              E.binary(raw['target']) == int(raw['status']=='heart_win') == source['target'],
              'invalid complete historical route')
    E.require(raw['checkpoint_sha256'] == identity['model_sha256'] and
              raw['engine_sha256'] == identity['engine_sha256'], 'wrong route runtime')
    for f in source['forced']:
        step = raw['prefix'][f['prefix_index']]
        E.require(step['kind']=='outside' and step['before']==f['fingerprint'] and
                  step['action']==f['action'], 'forced state/action differs')


def extract_family(x, job):
    spec = C.spec_for(x)
    graph = Graph(job['seed'])
    old = E.read(job['encoded_source'])
    E.require(E.sha(job['encoded_source']) == job['encoded_sha256'] and
              old['status']=='complete' and old['split']=='fit' and old['seed']==job['seed'] and
              old['state_rng_terminal_verified'], 'unaccepted encoded family')
    sources = job['sources']
    by_path = {s['path']:s for s in sources}
    raw_cache = {}
    counts = Counter()
    # E143 already checked these exact encodings, parent decisions and replays.
    for route in old['routes']:
        source = by_path[route['source_path']]
        E.require(source['scope']=='first_card' and source['sha256']==route['source_sha256'] and
                  E.sha(source['path'])==source['sha256'], 'encoded route binding differs')
        raw = E.read(source['path']); validate_raw(raw,source,job['seed'],x.identity)
        raw_cache[source['path']] = raw
        for row in route['rows']:
            step = raw['prefix'][row['prefix_index']]
            E.require(step['kind']=='outside' and row['actions'][row['chosen']]==step['action'],
                      'cached decision sequence differs')
            graph.state(step['before'],row,row['baseline'])
            counts['accepted_encoding_occurrences'] += 1
    counts['reused_unique_states'] = len(graph.states)
    parent = E.parent_model(x).eval()
    for source in sources:
        E.require(E.sha(source['path'])==source['sha256'], 'raw historical file changed')
        raw = raw_cache.pop(source['path']) if source['path'] in raw_cache else E.read(source['path'])
        validate_raw(raw,source,job['seed'],x.identity)
        forced = {f['prefix_index']:f for f in source['forced']}
        # A first-card source is already completely replayed by accepted E143.
        # Other scopes are restored with recorded combat actions, never search.
        if source['scope'] != 'first_card':
            gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,job['seed'],20)
            for i,step in enumerate(raw['prefix']):
                x.R.clock_input(gc,x.config)
                E.require(x.R.fingerprint(gc)==step['before'], 'replay pre-state/RNG differs')
                if step['kind']=='outside':
                    if step['before'] not in graph.state_ids:
                        row = C.encode(x,gc,spec)
                        actions = list(x.R.sts.get_legal_game_actions(gc))
                        _,descs,_ = x.A.build_choices(gc)
                        before = x.R.fingerprint(gc)
                        with x.H.torch.inference_mode():
                            choice = parent.choose(gc,x.A.obs_vec(gc),actions,descs)
                        E.require(before==x.R.fingerprint(gc), 'parent scoring changed state/RNG')
                        graph.state(step['before'],row,choice)
                        counts['newly_encoded_states'] += 1
                    row = graph.states[graph.state_ids[step['before']]]
                    if i in forced:
                        f = forced[i]
                        E.require(row['actions']==f['actions'] and row['descriptors']==f['descriptors'] and
                                  row['parent']==f['parent'], 'forced root menu/parent differs')
                    else:
                        E.require(row['actions'][row['parent']]==step['action'], 'unregistered change from frozen parent')
                x.R.replay_step(gc,step,x.config)
                counts['native_replayed_steps'] += 1
            x.R.clock_input(gc,x.config); x.P.verify_terminal(gc,raw)
        graph.route(source,raw)
        counts['raw_files'] += 1
        counts['raw_steps'] += len(raw['prefix'])
        counts['raw_outside_decisions'] += sum(s['kind']=='outside' for s in raw['prefix'])
    result = graph.finish(counts)
    E.require(result['multiple_successor_state_actions']==0,
              'same full state/action has multiple successors; inspect before defining sampling weights')
    return result


def registered(root):
    registration = E.read(root/'registration.json')
    E.require(E.sha(__file__)==registration['runner_sha256'], 'control-data runner changed')
    for p,h in registration['hashes'].items(): E.require(E.sha(p)==h,'registered input changed: '+p)
    plan = E.read(root/'protocol.json')
    E.require(plan['new_training_rollouts']==plan['MCTS_searches']==0, 'no collection/search budget')
    old = Path(plan['continuous_source']); accepted = E.read(old/'result-review.json')
    E.require(accepted['status']=='complete' and accepted['zero_faults'] and
              accepted['completion_sha256']==E.sha(old/'completion-verification.json'), 'continuous source not accepted')
    ranking = Path(plan['ranking_source']); proof = E.read(ranking/'result-review.json')
    E.require(proof['status']=='complete_recorded_screen_not_adopted' and
              proof['completion_sha256']==E.sha(ranking/'learning/completion.json'), 'branch source not accepted')
    roles = E.read(old/'fit-roles.json'); nodes = E.read(old/'fit-nodes.json')
    C.D.admitted_nodes(nodes,roles)
    E.require(len(roles)==1536, 'original fit roles differ')
    return plan,nodes,roles


def prepare_jobs(root):
    plan,nodes,roles = registered(root)
    old = Path(plan['continuous_source']); bundle = E.read(plan['branch_bundle'])
    E.require([r['seed'] for r in bundle['references']]==roles and
              all(r['split']=='fit' for r in bundle['references']), 'branch roles differ')
    trees = E.indexed(bundle['trees'],'seed','boss tree')
    bound = E.read(old/'completion-verification.json')['hashes']
    jobs = []
    for node in nodes:
        seed=node['seed']; encoded=old/'families'/f'{seed}.json.gz'
        jobs.append(dict(mode='prefix',seed=seed,runtime=plan['runtime'],encoded_source=str(encoded),
            encoded_sha256=bound[str(encoded)],
            sources=sources_for(node,trees.get(seed),bundle['states'],bundle['labels']),
            output=str(root/'index'/f'{seed}.json'),data_output=str(root/'families'/f'{seed}.json.gz')))
    E.require(Counter(s['scope'] for j in jobs for s in j['sources'])==plan['source_scope_counts'],
              'raw source coverage differs')
    return plan,jobs


def worker(job, config):
    try:
        x = C.D.runtime(job['runtime'])
        # A software guard makes accidental replanning fail instead of collect.
        def reject_search(*args,**kwargs): raise RuntimeError('E153 forbids new MCTS search')
        x.R.sts.resolve_battle_recorded = reject_search
        result = extract_family(x,job)
        x.H.write_json(Path(job['data_output']),result)
        compact = dict(status='complete',seed=job['seed'],states=len(result['states']),
            edges=len(result['edges']),routes=len(result['routes']),counts=result['counts'],
            multiple_successor_state_actions=result['multiple_successor_state_actions'],
            data_path=job['data_output'],data_sha256=E.sha(job['data_output']))
    except Exception:
        compact = dict(status='extraction_error',seed=job['seed'],error=traceback.format_exc())
    E.write(job['output'],compact)


def extract(root):
    plan,jobs = prepare_jobs(root); x=C.D.runtime(plan['runtime'])
    E.require(x.identity==plan['identity'] and C.spec_for(x)==E.read(root/'feature-spec.json'),
              'runtime identity or public features differ')
    config=dict(x.config,workers=plan['workers']); deadline=time.monotonic()+plan['timeout_seconds']
    summaries=[]
    for at in range(0,len(jobs),64):
        batch=jobs[at:at+64]
        rows=x.H.run_jobs(root,batch,config,f'E153_control_{at}',deadline,worker_fn=worker)
        E.require(len(rows)==len(batch), 'missing assigned family')
        E.require(all(r['status']=='complete' and r['seed']==j['seed'] for j,r in zip(batch,rows)),
                  'control extraction failed: '+str([r for r in rows if r['status']!='complete']))
        summaries.extend(rows)
    counts=Counter()
    for r in summaries: counts.update(r['counts'])
    E.write(root/'completion-verification.json',dict(status='complete',zero_faults=True,
        families=len(jobs),states=sum(r['states'] for r in summaries),edges=sum(r['edges'] for r in summaries),
        routes=sum(r['routes'] for r in summaries),counts=dict(counts),
        multiple_successor_state_actions=sum(r['multiple_successor_state_actions'] for r in summaries),
        new_training_rollouts=0,MCTS_searches=0,optimizer_updates=0,
        hashes={**{j['output']:E.sha(j['output']) for j in jobs},
                **{r['data_path']:r['data_sha256'] for r in summaries}}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('check','extract'))
    parser.add_argument('--study',type=Path,required=True)
    args=parser.parse_args(); root=args.study.resolve()
    prepare_jobs(root) if args.command=='check' else extract(root)
