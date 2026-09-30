"""Causal, base-card deck prefixes from public human run histories.

This is behavior supervision, not a counterfactual Heart-return dataset.
Final decks are audit targets only. HP, gold, final relics and future bosses
are deliberately absent: the archive does not reliably timestamp them at a
card reward. Unknown deck changes end the usable prefix.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import zipfile


ARCHIVE_URL = 'https://baalorlord.tv/archive/0/runs.zip'
RECIPE = dict(build='2022-12-18', minimum_families=200, minimum_choices=4000,
              minimum_late_families=40, minimum_late_choices=400)
STARTER = ['Strike_R']*5 + ['Defend_R']*4 + ['Bash', 'AscendersBane']
OPAQUE_RELICS = {"Pandora's Box", 'Astrolabe', 'Empty Cage', 'DollysMirror'}
COMBAT_EVENTS = {'Mysterious Sphere', 'Colosseum', 'Mushrooms', 'Dead Adventurer'}
NO_CARD = {'SKIP', 'Singing Bowl', 'SINGING_BOWL'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def put(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')


def base_card(name):
    return re.sub(r'\+\d+$', '', name)


def role(seed):
    value = int(hashlib.sha256(f'P204-human:{seed}'.encode()).hexdigest()[:8], 16) % 10
    return 'fit' if value < 7 else 'validation' if value < 9 else 'held'


class UnknownDeck(ValueError):
    pass


def remove(deck, names):
    for name in names:
        name = base_card(name)
        if deck[name] <= 0:
            raise UnknownDeck('removing_absent_card:'+name)
        deck[name] -= 1
        if deck[name] == 0: del deck[name]


def update(deck, removed=(), transformed=(), obtained=()):
    # A transform logs old identities separately from newly obtained identities.
    remove(deck, [*removed, *transformed])
    deck.update(base_card(n) for n in obtained)


def extract(run, is_card):
    """Return evidence before the first unresolved deck mutation.

    `is_card` is a frozen native-ID lookup; no outcome or final deck determines
    a feature. End-of-run deck comparison is returned separately for admission.
    Base identities intentionally ignore permanent upgrade count and misc.
    """
    deck = Counter(STARTER); rows = []; stop = None
    neow = run.get('neow_bonus_log')
    if not isinstance(neow, dict):
        return dict(rows=[], stop='missing_neow_log', stop_floor=0, terminal_check=None)
    try:
        update(deck, neow.get('cardsRemoved', []), neow.get('cardsTransformed', []), neow.get('cardsObtained', []))
    except UnknownDeck as error:
        return dict(rows=[], stop=str(error), stop_floor=0, terminal_check=None)
    neow_relics = set(neow.get('relicsObtained', []))
    if neow_relics & OPAQUE_RELICS:
        return dict(rows=[], stop='opaque_neow_relic', stop_floor=0, terminal_check=None)
    if 'Calling Bell' in neow_relics and 'CurseOfTheBell' not in deck:
        # No invented acquisition: require the Neow log to account for the curse.
        return dict(rows=[], stop='unlogged_neow_bell_curse', stop_floor=0, terminal_check=None)

    events = defaultdict(list); fires = defaultdict(list); choices = defaultdict(list)
    relics = defaultdict(list); bought = defaultdict(list); purged = defaultdict(list)
    for row in run.get('event_choices', []): events[int(row['floor'])].append(row)
    for row in run.get('campfire_choices', []): fires[int(row['floor'])].append(row)
    for row in run.get('card_choices', []): choices[int(row['floor'])].append(row)
    for row in run.get('relics_obtained', []): relics[int(row['floor'])].append(row['key'])
    for i, row in enumerate(run.get('boss_relics', [])):
        relics[(17, 34)[i]].append(row['picked'])
    purchase_names, purchase_floors = run.get('items_purchased', []), run.get('item_purchase_floors', [])
    purge_names, purge_floors = run.get('items_purged', []), run.get('items_purged_floors', [])
    if len(purchase_names) != len(purchase_floors) or len(purge_names) != len(purge_floors):
        return dict(rows=[], stop='unaligned_shop_logs', stop_floor=0, terminal_check=None)
    for n, f in zip(purchase_names, purchase_floors):
        if is_card(base_card(n)): bought[int(f)].append(n)
    for n, f in zip(purge_names, purge_floors): purged[int(f)].append(n)
    stop_floor = None
    for floor in range(1, int(run['floor_reached'])+1):
        before_floor = len(rows)
        try:
            if set(relics[floor]) & OPAQUE_RELICS:
                raise UnknownDeck('opaque_relic')
            if 'Calling Bell' in relics[floor]:
                raise UnknownDeck('unlogged_bell_curse')
            # Event-generated reward menus do not establish whether event gains
            # occur before or after a particular menu. Stop, rather than guess.
            if choices[floor] and any(e['event_name'] not in COMBAT_EVENTS or
                                     e.get('cards_obtained') or e.get('cards_removed') or
                                     e.get('cards_transformed') for e in events[floor]):
                raise UnknownDeck('ambiguous_event_reward_order')
            for e in events[floor]:
                update(deck, e.get('cards_removed', []), e.get('cards_transformed', []), e.get('cards_obtained', []))
            remove(deck, purged[floor]); deck.update(base_card(n) for n in bought[floor])
            for fire in fires[floor]:
                if fire['key'] == 'PURGE': remove(deck, [fire['data']])
            if any(not is_card(n) for n in deck): raise UnknownDeck('unknown_deck_card')
            ambiguous_floor = bool(bought[floor] or purged[floor] or fires[floor])
            for sequence, choice in enumerate(choices[floor]):
                picked = choice['picked']; offered = list(choice['not_picked'])
                if picked not in NO_CARD: offered.append(picked)
                if not offered or any(not is_card(base_card(n)) for n in offered):
                    raise UnknownDeck('unknown_reward_card')
                # Order is not preserved by .run: canonicalize the set and never
                # provide the historical selected position as a feature.
                offered = sorted(set(offered))
                if not ambiguous_floor:
                    rows.append(dict(floor=floor, act=1 if floor<=17 else 2 if floor<=34 else 3 if floor<=51 else 4,
                        sequence=sequence, deck=dict(sorted(deck.items())), offered=offered,
                        picked='SKIP' if picked in NO_CARD else picked))
                if picked not in NO_CARD: deck[base_card(picked)] += 1
        except UnknownDeck as error:
            del rows[before_floor:]
            stop, stop_floor = str(error), floor
            break
    final = Counter(base_card(n) for n in run.get('master_deck', []))
    terminal_check = None if stop else deck == final
    return dict(rows=rows, stop=stop, stop_floor=stop_floor, terminal_check=terminal_check,
                reconstructed=dict(sorted(deck.items())), terminal_expected=dict(sorted(final.items())))


def vocabulary(runtime, archive):
    import heart_trajectory_value_data as D
    x = D.runtime(runtime)
    names = set()
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if not name.endswith('.run'): continue
            run = json.loads(z.read(name))
            if run.get('character_chosen') != 'IRONCLAD': continue
            for card in run.get('master_deck', []): names.add(base_card(card))
            for c in run.get('card_choices', []):
                names.update(base_card(n) for n in [c['picked'], *c['not_picked']] if n not in NO_CARD)
    aliases = dict(Strike_R='STRIKE_RED', Defend_R='DEFEND_RED', AscendersBane='ASCENDERS_BANE')
    accepted, rejected = {}, []
    enum_names = {re.sub('[^A-Z0-9]', '', n): n for n in x.R.sts.CardId.__members__}
    for name in sorted(names | set(STARTER)):
        key = re.sub('[^A-Z0-9]', '', name.upper())
        mapped = aliases.get(name, enum_names.get(key, name))
        try:
            value = int(x.R.sts.card_id_from_name(mapped))
            if value <= 0: raise ValueError('invalid native ID')
            accepted[name] = value
        except (ValueError, RuntimeError): rejected.append(name)
    return dict(names=accepted, rejected=rejected, card_cap=x.A.CARD_CAP, runtime_identity=x.identity)


def prepare(root, runtime):
    archive = root/'source/baalorlord-profile0-runs.zip'
    if (root/'protocol.json').exists(): raise ValueError('protocol exists')
    vocab = vocabulary(str(runtime), archive); put(root/'vocabulary.json', vocab)
    plan = dict(experiment='P204', recipe=RECIPE, source_url=ARCHIVE_URL,
        archive_sha256=sha(archive), runner_sha256=sha(__file__), vocabulary_sha256=sha(root/'vocabulary.json'),
        runtime=str(runtime), training_signal='Human observed card reward choices, including losses; no terminal-return labels.',
        scope='A20 Ironclad, current build, non-daily/non-trial/non-endless/non-seeded, no Prismatic Shard. One archive snapshot; all exclusions counted.',
        inputs='Base card identity counts before the choice, act/floor, offered card identities/upgrades. No seed, win flag, final deck/relics, future encounters, HP/gold snapshots or teacher-chosen menu order.',
        uncertainty='Unknown deck-changing relic or ambiguous event/reward ordering ends the usable prefix. Full reconstructed routes require terminal base-card multiset equality; stopped prefixes retain their explicit limitation. Same-floor shop/campfire choices omitted.',
        roles='SHA256(P204-human:<uint64 seed>) modulo10:0..6 fit,7..8 validation,9 held. Duplicate seed families remain one role. No outcome selection.',
        data_gate='At least200 families,4000 choices,40 families and400 choices in Acts3/4. This is source usability, not action quality or win rate.',
        budgets=dict(new_games=0,optimizer_updates=0), policy_adoption=False,
        next='If data admitted, freeze one student and an act-only human-prior control, then test complete natural games with the original engine. Source imitation does not prove superiority to the simulator parent.')
    put(root/'protocol.json', plan)


def collect(root):
    plan = json.loads((root/'protocol.json').read_text()); archive=root/'source/baalorlord-profile0-runs.zip'
    assert plan['runner_sha256']==sha(__file__) and plan['archive_sha256']==sha(archive)
    assert plan['recipe']==RECIPE and plan['vocabulary_sha256']==sha(root/'vocabulary.json')
    vocab=json.loads((root/'vocabulary.json').read_text())['names']; audit=[]; all_rows=[]; exclusions=Counter(); seen={}
    with zipfile.ZipFile(archive) as z:
        for name in sorted(z.namelist()):
            if not name.endswith('.run'): continue
            raw=z.read(name); run=json.loads(raw)
            reason = ('character' if run.get('character_chosen')!='IRONCLAD' else
                      'ascension' if run.get('ascension_level')!=20 else
                      'build' if run.get('build_version')!=RECIPE['build'] else
                      'custom_or_seeded' if any(run.get(k) for k in ('is_daily','is_trial','is_endless','chose_seed')) else
                      'prismatic' if any(re.sub('[^a-z]','',r.lower())=='prismaticshard' for r in run.get('relics',[])) else None)
            if reason: exclusions[reason]+=1; continue
            seed=int(run['seed_played'])%(1<<64); extracted=extract(run,lambda n:n in vocab)
            status='full_checked' if extracted['terminal_check'] else 'bounded_prefix' if extracted['stop'] else 'rejected_final_mismatch'
            valid=status!='rejected_final_mismatch'
            row=dict(member=name,sha256=hashlib.sha256(raw).hexdigest(),family=seed,role=role(seed),status=status,
                stop=extracted['stop'],stop_floor=extracted['stop_floor'],terminal_check=extracted['terminal_check'],
                usable_choices=len(extracted['rows']) if valid else 0,
                reconstructed=extracted['reconstructed'] if 'reconstructed' in extracted else {},
                terminal_expected=extracted.get('terminal_expected',{}))
            audit.append(row)
            if valid:
                for choice in extracted['rows']:
                    key=(seed,choice['floor'],choice['sequence'])
                    signature=json.dumps(choice,sort_keys=True)
                    if key in seen:
                        if seen[key]!=signature: raise ValueError('conflicting duplicate human family')
                        continue
                    seen[key]=signature; all_rows.append(dict(family=seed,role=role(seed),source=name,**choice))
    families={r['family'] for r in all_rows}; late=[r for r in all_rows if r['act']>=3]
    gate=len(families)>=RECIPE['minimum_families'] and len(all_rows)>=RECIPE['minimum_choices'] and len({r['family'] for r in late})>=RECIPE['minimum_late_families'] and len(late)>=RECIPE['minimum_late_choices']
    put(root/'source-audit.json',audit); put(root/'choices.json',all_rows)
    result=dict(status='complete',source_runs=len(audit)+sum(exclusions.values()),exclusions=dict(exclusions),
        eligible_runs=len(audit),source_statuses=dict(Counter(r['status'] for r in audit)),
        stops=dict(Counter(r['stop'] for r in audit if r['stop'])),choices=len(all_rows),families=len(families),
        by_act=dict(Counter(r['act'] for r in all_rows)),late_families=len({r['family'] for r in late}),
        by_role={s:dict(families=len({r['family'] for r in all_rows if r['role']==s}),choices=sum(r['role']==s for r in all_rows)) for s in ('fit','validation','held')},
        gate_passed=gate,new_games=0,optimizer_updates=0,policy_adoption=False,
        hashes={str(root/n):sha(root/n) for n in ('protocol.json','vocabulary.json','source-audit.json','choices.json')})
    put(root/'data-result.json',result); print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('prepare','collect'));p.add_argument('--root',type=Path,required=True);p.add_argument('--runtime',type=Path)
    a=p.parse_args();root=a.root.resolve()
    if a.command=='prepare':prepare(root,a.runtime.resolve())
    else:collect(root)
