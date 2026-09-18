"""Replay frozen winning actions in isolated original Java, without state import."""
import argparse
from collections import Counter
import gzip
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
import subprocess
import struct
from winner_ui import knowing_skull_intro, dream_catcher_close, terminal_headbutt_selection


def read(path):
    with gzip.open(path, 'rt') if str(path).endswith('.gz') else Path(path).open() as f:
        return json.load(f)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def setup(root):
    plan = read(root / 'plan.json')
    cohort = Path(plan['source_cohort'])
    runtime = Path(plan['source_runtime']) if 'source_runtime' in plan else cohort / 'candidate'
    report = Path(plan['source_report']) if 'source_report' in plan else cohort / 'report.json'
    assert sha(report) == plan['source_report_sha256']
    assert sha(runtime / 'model.pt') == plan['candidate_model_sha256']
    assert sha(runtime / 'engine/slaythespire.cpython-312-darwin.so') == plan['engine_sha256']
    os.environ['HEART_BRANCH_RUNTIME'] = str(runtime)
    os.environ['ALIGNMENT_BUILD'] = str(runtime / 'engine')
    os.environ['ALIGNMENT_COMPACT_RECORDS'] = '1'
    sys.path.insert(0, str(runtime))
    import heart_branch_training as T
    T.H.torch.set_num_threads(1)
    T.S.verify_files(runtime)
    alignment = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(alignment / 'oracle'))
    sys.path.insert(0, str(alignment / 'tests'))
    Q = importlib.import_module('run')
    C = importlib.import_module('compare_cards')
    D = importlib.import_module('replay_trace')
    assert C.sts is T.R.sts
    Q.common.OUT = root / 'original'
    for seed, expected in plan.get('source_episode_sha256', {}).items():
        assert sha(runtime / f'episodes/{seed}.json.gz') == expected
    return plan, runtime, T, Q, C, D


def convert(root, runtime, seed, T):
    source = runtime / f'episodes/{seed}.json.gz'
    row = read(source)
    assert row['seed'] == seed and row['status'] == 'heart_win'
    config = read(runtime / 'config.json')
    gc = T.R.sts.GameContext(T.R.sts.CharacterClass.IRONCLAD, seed, 20)
    steps = []
    for index, old in enumerate(row['prefix']):
        T.R.clock_input(gc, config)
        assert T.R.fingerprint(gc) == old['before']
        step = dict(prefix_index=index, floor=gc.floor_num, hp=gc.cur_hp,
                    screen=int(gc.screen_state), before=old['before'],
                    play_time_seconds=gc.floor_num * config['seconds_per_floor'],
                    actions=old['actions'] if old['kind'] == 'battle' else [old['action']])
        if old['kind'] == 'battle':
            step['battle_outcome'] = old['outcome']
        steps.append(step)
        T.R.replay_step(gc, old, config)
    T.R.clock_input(gc, config)
    T.P.verify_terminal(gc, row)
    result = dict(seed=seed, controlled_fixture=False, steps=steps,
                  source_episode=str(source), source_episode_sha256=sha(source),
                  expected_terminal={k: row[k] for k in ('status', 'act', 'floor', 'hp', 'keys', 'terminal_fingerprint')})
    path = root / f'traces/{seed}.json'
    if path.exists():
        assert read(path) == result
    else:
        write(path, result)
    return result, config, path


def one(root, seed, attempt, modules):
    plan, cohort, T, Q, C, D = modules
    assert seed in plan['seeds']
    trace, config, trace_path = convert(root, cohort, seed, T)
    name = f'{seed}-{attempt:02d}'
    d = root / 'original' / name
    if (d / 'result.json').exists():
        result = read(d / 'result.json')
        assert result['source_episode_sha256'] == trace['source_episode_sha256']
        return result
    d, instance, metadata = Q.prepare(name)
    assert sha(instance / 'desktop-1.0.jar') == plan['reference_game_sha256']
    identity = {'driver_sha256': sha(__file__), 'trace_sha256': sha(trace_path),
                'original_game_sha256': sha(instance / 'desktop-1.0.jar'),
                'original_instance_manifest_sha256': sha(instance / 'instance.json'),
                'engine_sha256': sha(T.R.sts.__file__),
                'harness_sha256': {str(p): sha(p) for p in [Path(Q.__file__), Path(C.__file__),
                    Path(D.__file__), Path(D.outside_differences.__code__.co_filename),
                    Path(D.extras.__code__.co_filename), Path(C.bridge.__file__),
                    Path(knowing_skull_intro.__code__.co_filename), Q.ROOT / 'oracle/AlignmentProbe.java']}}
    write(d / 'identity.json', identity)

    class WinnerReplay(D.TraceReplay):
        def __init__(self, *args):
            super().__init__(*args)
            self.clock = 0
            self.prefix_index = -1
            self.combat_action_index = None
            self.last_comparison = None

        def call(self, command):
            screen = self.view.get('game', {}).get('screen_state', {})
            if command == 'confirm' and screen.get('for_transform') and screen.get('confirm_up'):
                # Use the same external preview-frame input as the simulator.
                # The native isolated runner's delta is observed, never assigned.
                frames = config.get('transform_preview_frames', 1)
                delta = config.get('transform_frame_delta_seconds', 1 / 60)
                observed = self.view.get('grid_transform_preview', {}).get('delta')
                if observed is not None and struct.pack('f', observed) != struct.pack('f', delta):
                    raise ValueError('native preview delta differs from frozen input')
                if frames > 1:
                    self.call('wait ' + str(frames - 1))
            self.view = self.p.call('command', command=command, play_time_seconds=self.clock)
            self.rows.append({'command': command, 'floor': self.view['game']['floor'],
                              'screen': self.view['game']['screen_type'],
                              'prefix_index': self.prefix_index, 'play_time_seconds': self.clock})
            assert self.view['rule_input_play_time'] == self.clock
            return self.view

        def card_signature(self, card, native, b):
            value = C.original_card(card) if native else C.card(card)
            skill = card['type'] == 'SKILL' if native else card.type == C.sts.CardType.SKILL
            if (skill and value[2] >= 0 and value[3] >= 0
                    and b.player.has_status(C.sts.PlayerStatus.CORRUPTION)
                    and any(p['id'] == 'Corruption' for p in self.view['game']['combat_state']['player']['powers'])):
                # Corruption persists for this battle and overrides skill energy
                # cost, including Exhume returns. Keep X/unplayable costs distinct.
                # Normalize comparison values only; neither game's cards change.
                return (*value[:2], 0, 0, *value[4:])
            return value

        def check(self, b=None):
            g = self.view['game']
            if b is None:
                diff = D.outside_differences(self.view, self.gc)
                if hasattr(self.gc, 'transform_preview_state'):
                    timer = self.view['grid_transform_preview']['timer']
                    expected = struct.unpack('f', struct.pack('f', timer))[0]
                    actual = self.gc.transform_preview_state['timer']
                    if expected != actual:
                        diff['transform_preview_timer'] = {'original': expected, 'simulator': actual}
                if g['screen_type'] == 'BOSS_REWARD':
                    wanted = [C.sts.relic_id_from_name(x['id']) for x in g['screen_state']['relics']]
                    actual = list(self.gc.boss_relics)
                    if wanted != actual:
                        diff['boss_relic_offers'] = {'original': wanted, 'simulator': actual}
            elif g['room_phase'] == 'COMBAT' and 'combat_state' in g and b.outcome == C.sts.Outcome.UNDECIDED:
                if b.input_state != C.sts.InputState.PLAYER_NORMAL or g['screen_type'] != 'NONE':
                    # Java can pause its action queue for a choice before queued
                    # power changes resolve (e.g. waking Lagavulin via Headbutt).
                    # Validate the selected card through the UI, then compare
                    # complete state when both action queues have resolved.
                    self.rows[-1]['comparison_boundary'] = 'card choice pending; full state checked after resolution'
                    return
                wanted, actual = C.original(g), C.simulator(b)
                for pile_name in ('hand', 'draw_pile', 'discard_pile', 'exhaust_pile'):
                    native_cards = g['combat_state'][pile_name]
                    normalized_native = [self.card_signature(c, True, b) for c in native_cards]
                    normalized_sim = [self.card_signature(c, False, b) for c in getattr(b, pile_name)]
                    if wanted[pile_name] != actual[pile_name] and normalized_native == normalized_sim:
                        self.rows[-1].setdefault('corruption_effective_cost_equivalence', {})[pile_name] = {
                            'original': wanted[pile_name], 'simulator': actual[pile_name]}
                    wanted[pile_name] = normalized_native
                    actual[pile_name] = normalized_sim
                # Exhaust cards are selected by identity, not dealt/shuffled in
                # their storage order. Keep all card values, including costs.
                if wanted['exhaust_pile'] != actual['exhaust_pile'] and sorted(wanted['exhaust_pile']) == sorted(actual['exhaust_pile']):
                    self.rows[-1]['equivalent_exhaust_order'] = True
                wanted['exhaust_pile'] = sorted(wanted['exhaust_pile'])
                actual['exhaust_pile'] = sorted(actual['exhaust_pile'])
                wanted['rng'] = {k: C.bridge.rng_snapshot(self.view['rng'][v]) for k, v in C.RNG_NAMES.items()}
                actual['rng'] = dict(b.rng_states)
                diff = {k: {'original': wanted[k], 'simulator': actual[k]} for k in wanted if wanted[k] != actual[k]}
                extra = D.extras(g, b)
                if 'player_powers' in extra:
                    pair = extra['player_powers']
                    # No Draw is a presence flag and clears completely at turn
                    # end; an internal stack count has no gameplay meaning.
                    for powers in pair.values():
                        if powers.get('NO_DRAW', 0) > 0:
                            powers['NO_DRAW'] = 1
                    if pair['original'] == pair['simulator']:
                        del extra['player_powers']
                live_native = [m for m in g['combat_state']['monsters'] if m['current_hp'] > 0 or m.get('half_dead')]
                if (any(r['id'] == 'Runic Dome' for r in g['relics']) and live_native
                        and all(m.get('move_id') is None for m in live_native)):
                    self.rows[-1]['original_intents_unobserved'] = 'Runic Dome hides intents in the original observer; compare resolved effects and RNG'
                    pair = extra.get('monster_powers_and_intents')
                    if pair:
                        for side in pair:
                            pair[side] = [(row[0], row[2]) for row in pair[side]]
                        if pair['original'] == pair['simulator']:
                            del extra['monster_powers_and_intents']
                diff.update(extra)
            else:
                self.rows[-1]['comparison_boundary'] = 'battle exit compared after simulator exit_battle'
                return
            self.record_comparison(diff)

        def record_comparison(self, diff):
            g = self.view['game']
            self.rows[-1]['differences'] = diff
            self.last_comparison = {'prefix_index': self.prefix_index, 'command_index': len(self.rows)-1,
                                    'combat_action_index': self.combat_action_index,
                                    'floor': g['floor'], 'screen': g['screen_type'], 'differences': diff}
            if diff:
                write(self.d / 'first-mismatch.json', self.last_comparison)
                raise ValueError('rules mismatch ' + str(list(diff)))

        def choose_card_reward(self, a):
            g = self.view['game']
            assert g['screen_type'] == 'CARD_REWARD'
            wanted = [(C.bridge.card_snapshot(c)['id'], c['upgrades']) for c in g['screen_state']['cards']]
            actual = [(int(c.id), int(c.upgrade_count)) for c in self.gc.rewards['cards'][a.idx1]]
            self.record_comparison({} if wanted == actual else {
                'card_reward_offers': {'original': wanted, 'simulator': actual}})
            choice = g['choice_list'].index('bowl') if a.idx2 == 5 else a.idx2
            self.call('choose ' + str(choice))
            a.execute(self.gc)

        def align(self):
            g = self.view['game']
            if self.gc.screen_state == C.sts.ScreenState.EVENT_SCREEN:
                key = (g['floor'], g['screen_state'].get('event_id'))
                if (self.gc.event_id == 'Knowing Skull'
                        and knowing_skull_intro(self.view, self.event_steps.get(key, 0))):
                    self.check()
                    self.call('choose 0')
                    self.check()
                    self.rows[-1]['ui_boundary'] = 'Knowing Skull introduction; no reward selected'
                    g = self.view['game']
                for _ in range(2):
                    if (g['screen_type'] == 'EVENT' and g['screen_state'].get('event_id') == 'Match and Keep!'
                            and g.get('choice_list') in (['继续'], ['玩小游戏'])):
                        self.call('choose 0')
                        g = self.view['game']
                    else:
                        break
            if (self.gc.screen_state == C.sts.ScreenState.SHOP_ROOM
                    and g['screen_type'] == 'MAP' and g['room_type'] == 'ShopRoom'
                    and g['floor'] == self.gc.floor_num):
                # Closing Cauldron's reward list opens the map; returning reopens
                # the same shop without taking a path or importing game state.
                self.call('return')
                g = self.view['game']
            if (self.gc.screen_state == C.sts.ScreenState.SHOP_ROOM
                    and g['screen_type'] == 'COMBAT_REWARD' and g['room_type'] == 'ShopRoom'
                    and g['floor'] == self.gc.floor_num):
                # After a purge the original can reopen Cauldron's remaining
                # reward screen. Dismiss its native cancel button once more.
                self.call('cancel_shop_reward')
            super().align()

        def outside(self, a):
            self.combat_action_index = None
            if (self.gc.screen_state == C.sts.ScreenState.EVENT_SCREEN
                    and self.gc.event_id == 'Match and Keep!' and not a.is_potion_action):
                self.align()
                self.check()
                if not a.is_valid(self.gc):
                    raise ValueError('recorded memory-match action is illegal')
                options = [x for x in C.sts.get_legal_game_actions(self.gc) if not x.is_potion_action]
                choice = next(i for i, x in enumerate(options) if x.bits == a.bits)
                if len(options) != len(self.view['game']['choice_list']):
                    raise ValueError('memory-match option count differs')
                self.call('choose ' + str(choice))
                a.execute(self.gc)
                return
            if (self.gc.screen_state == C.sts.ScreenState.SHOP_ROOM
                    and not a.is_potion_action and int(a.rewards_action_type) == 4):
                self.align()
                self.check()
                if not a.is_valid(self.gc):
                    raise ValueError('recorded shop relic action is illegal')
                relic_id, price = self.gc.get_shop_relics()[a.idx1]
                g = self.view['game']
                stock = g['screen_state']['relics']
                matches = [r for r in stock if C.sts.relic_id_from_name(r['id']) == int(relic_id)
                           and r['price'] == price]
                if len(matches) != 1:
                    self.record_comparison({'shop_relic_choice': {
                        'original': [(C.sts.relic_id_from_name(r['id']), r['price']) for r in stock],
                        'simulator_selected': (int(relic_id), price)}})
                choice = g['choice_list'].index(matches[0]['name'].lower())
                self.call('choose ' + str(choice))
                a.execute(self.gc)
                return
            if self.gc.screen_state == C.sts.ScreenState.REWARDS and not a.is_potion_action:
                if not a.is_valid(self.gc):
                    raise ValueError('recorded reward action is illegal')
                g = self.view['game']
                kind = int(a.rewards_action_type)
                if (kind == 6 and g['floor'] == self.gc.floor_num
                        and dream_catcher_close(self.view, self.gc.rewards)):
                    self.check()
                    self.call('proceed')
                    a.execute(self.gc)
                    self.check()
                    self.rows[-1]['ui_boundary'] = 'Dream Catcher reward closed at completed rest'
                    return
                if g['screen_type'] == 'CARD_REWARD':
                    # Neow opens the card choices without a combat-reward list.
                    self.check()
                    if kind == 0:
                        self.choose_card_reward(a)
                    elif kind == 6:
                        self.call('skip')
                        a.execute(self.gc)
                    else:
                        raise ValueError('non-card reward action on direct card screen')
                    return
                if g.get('neow', {}).get('stage') == 'leave' and kind == 6:
                    self.check()
                    self.call('choose 0')
                    a.execute(self.gc)
                    return
                if (kind == 6 and g['screen_type'] == 'COMBAT_REWARD'
                        and g['room_type'] == 'ShopRoom'):
                    # The shop relic reward uses a visible native cancel button
                    # omitted by CommunicationMod. The probe clicks that button.
                    self.check()
                    self.call('cancel_shop_reward')
                    a.execute(self.gc)
                    return
                if kind == 0:
                    self.align()
                    self.check()
                    rewards = self.view['game']['screen_state']['rewards']
                    choices = [i for i, r in enumerate(rewards) if r['reward_type'] == 'CARD']
                    self.call('choose ' + str(choices[a.idx1]))
                    self.choose_card_reward(a)
                    return
            super().outside(a)

        def combat(self, row):
            self.align()
            b = C.sts.BattleContext()
            b.init(self.gc)
            self.check(b)
            for action_index, raw in enumerate(row['actions']):
                self.combat_action_index = action_index
                a = C.sts.SearchAction.from_bits(raw & 0xffffffff)
                if not a.is_valid(b):
                    raise ValueError('recorded combat action is illegal')
                played_headbutt = (a.action_type == C.sts.SearchActionType.CARD
                                   and b.hand[a.source_idx].id == C.sts.CardId.HEADBUTT)
                snap = C.bridge.build_snapshot(self.view['game'])
                if a.action_type == C.sts.SearchActionType.POTION:
                    index, target = int(a.source_idx), int(a.target_idx)
                    if target > 5:
                        command = f'potion discard {index}'
                    elif self.view['game']['potions'][index]['id'] in ('Explosive Potion', 'SmokeBomb'):
                        # The observer labels thrown AoE potions as targeted;
                        # Both original use methods ignore the enemy target. Supply a live
                        # native enemy for the protocol without mapping dummy 0.
                        target = next(i for i, m in enumerate(self.view['game']['combat_state']['monsters'])
                                      if m['current_hp'] > 0 and not m.get('is_gone'))
                        command = f'potion use {index} {target}'
                    elif self.view['game']['potions'][index]['requires_target']:
                        target = snap['target_map'][target]
                        if target < 0:
                            raise ValueError('targeted potion points to an empty monster slot')
                        command = f'potion use {index} {target}'
                    else:
                        command = f'potion use {index}'
                    self.call(command)
                elif a.action_type in (C.sts.SearchActionType.CARD, C.sts.SearchActionType.END_TURN):
                    self.call(C.bridge.action_command(a, b, snap).lower())
                elif a.action_type == C.sts.SearchActionType.SINGLE_CARD_SELECT:
                    legal = C.sts.get_legal_actions(b)
                    index = next(i for i, option in enumerate(legal) if option.bits == a.bits)
                    screen = self.view['game']['screen_type']
                    if screen == 'GRID':
                        options = self.view['game']['screen_state']['cards']
                        visible = [self.card_signature(c, True, b) for c in options]
                        targets = set()
                        combat = self.view['game']['combat_state']
                        for pile_name in ('exhaust_pile', 'discard_pile', 'draw_pile', 'hand'):
                            pile = getattr(b, pile_name)
                            if not all(0 <= option.select_idx < len(pile) for option in legal):
                                continue
                            candidates = [self.card_signature(pile[option.select_idx], False, b) for option in legal]
                            if sorted(candidates) != sorted(visible):
                                continue
                            native_pile = combat[pile_name]
                            source_cards = [self.card_signature(c, False, b) for c in pile]
                            native_cards = [self.card_signature(c, True, b) for c in native_pile]
                            if source_cards == native_cards:
                                chosen = native_pile[a.select_idx]
                            elif pile_name == 'exhaust_pile':
                                target = self.card_signature(pile[a.select_idx], False, b)
                                occurrence = source_cards[:a.select_idx].count(target)
                                matches = [c for c in native_pile if self.card_signature(c, True, b) == target]
                                if occurrence >= len(matches):
                                    continue
                                chosen = matches[occurrence]
                            else:
                                continue
                            # Grid display can be sorted or randomly arranged.
                            # Match the exact original source-card UUID, including
                            # the selected copy among otherwise identical cards.
                            targets.add(chosen['uuid'])
                        if len(targets) == 1:
                            uuid = next(iter(targets))
                            index = next(i for i, c in enumerate(options) if c['uuid'] == uuid)
                        elif len(targets) > 1:
                            raise ValueError('ambiguous grid source pile')
                    if (screen == 'CARD_REWARD' and a.select_idx == 3
                            and len(self.view['game']['screen_state']['cards']) == 3
                            and 'skip' in self.view['available_commands']):
                        self.call('skip')  # Nilry's Codex optional fourth action.
                    else:
                        self.call('choose ' + str(index))
                else:
                    screen = self.view['game']['screen_state']
                    options = screen.get('cards', screen.get('hand', []))
                    chosen = [options[i]['uuid'] for i in reversed(a.selected_idxs)]
                    for uuid in chosen:
                        screen = self.view['game']['screen_state']
                        options = screen.get('cards', screen.get('hand', []))
                        self.call('choose ' + str(next(i for i, c in enumerate(options) if c['uuid'] == uuid)))
                    if 'confirm' in self.view['available_commands']:
                        self.call('confirm')
                a.execute(b)
                if terminal_headbutt_selection(self.view, played_headbutt,
                                                b.outcome == C.sts.Outcome.PLAYER_VICTORY):
                    # The leader is dead and every survivor is a minion. The
                    # original queue waits for moving a discard card before
                    # completing victory; this choice cannot affect a later turn.
                    self.call('choose 0')
                    self.rows[-1]['ui_boundary'] = 'terminal Headbutt discard placement before minion-leader victory'
                if ('confirm' in self.view['available_commands']
                        and (b.input_state == C.sts.InputState.PLAYER_NORMAL
                             or 'choose' not in self.view['available_commands'])):
                    self.call('confirm')
                self.check(b)
            if int(b.outcome) != row['battle_outcome']:
                raise ValueError('recorded combat outcome changed')
            b.exit_battle(self.gc)

        def run(self):
            self.p.call('observe', timeout_seconds=180)
            self.call('start ironclad 20 ' + C.sts.get_seed_str(seed))
            for index, step in enumerate(trace['steps']):
                self.prefix_index = index
                T.R.clock_input(self.gc, config)
                self.clock = step['play_time_seconds']
                if T.R.fingerprint(self.gc) != step['before']:
                    raise ValueError('source simulator prefix changed at ' + str(index))
                if step['screen'] == 9:
                    self.combat(step)
                else:
                    for bits in step['actions']:
                        self.outside(C.sts.GameAction(bits & 0xffffffff))
                write(self.d / 'progress.json', {'prefix_index': index, 'total_prefixes': len(trace['steps']),
                    'floor': self.gc.floor_num, 'hp': self.gc.cur_hp, 'commands': len(self.rows)})
            for _ in range(10):
                if self.view['game']['screen_type'] == 'GAME_OVER':
                    break
                if 'proceed' not in self.view['available_commands']:
                    raise ValueError('missing original terminal')
                self.call('proceed')
            self.check()
            terminal = self.view['game']
            assert terminal['act'] == 4 and terminal['screen_type'] == 'GAME_OVER' and terminal['screen_state']['victory']
            assert [self.view[k] for k in ('ruby', 'emerald', 'sapphire')] == [True] * 3
            T.R.clock_input(self.gc, config)
            T.P.verify_terminal(self.gc, trace['expected_terminal'])
            return {'status': 'original_heart_trace_matched', 'floor': self.gc.floor_num,
                    'hp': self.gc.cur_hp, 'original_terminal': terminal['screen_state']}

    runner = WinnerReplay(Q.Probe(instance), trace, d)
    started = time.monotonic()
    result = {}
    try:
        write(d / 'launch.json', Q.launch(instance))
        result = runner.run()
    except Exception as error:
        diff = (runner.last_comparison or {}).get('differences')
        result = {'status': 'rules_mismatch' if diff else 'adapter_or_runtime_error',
                  'error': str(error), 'traceback': traceback.format_exc(),
                  'first_mismatch': runner.last_comparison if diff else None,
                  'prefix_index': runner.prefix_index,
                  'floor': runner.view.get('game', {}).get('floor')}
    finally:
        with gzip.open(d / 'last-state.json.gz', 'wt') as f:
            json.dump(runner.view, f)
        result.update(seed=seed, attempt=attempt, source_episode_sha256=trace['source_episode_sha256'],
                      identity_sha256=sha(d / 'identity.json'), resynchronized=False, controlled_fixture=False,
                      seconds=time.monotonic()-started, commands=len(runner.rows))
        write(d / 'comparisons.json', runner.rows)
        write(d / 'result.json', result)
        Q.stop(instance)
        if Q.instance_processes(instance):
            Q.stop(instance, force=True)
        write(d / 'cleanup.json', {'remaining': Q.instance_processes(instance)})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--seed', type=int)
    p.add_argument('--seed-file', type=Path, help='Explicit remaining/retry subset of the frozen plan')
    p.add_argument('--attempt', type=int, default=1)
    p.add_argument('--workers', type=int, default=4)
    a = p.parse_args()
    root = a.root.resolve()
    modules = setup(root)
    if a.seed is not None:
        result = one(root, a.seed, a.attempt, modules)
        print(json.dumps({k: v for k, v in result.items() if k not in ('traceback', 'first_mismatch')}, ensure_ascii=False), flush=True)
        return
    assert 1 <= a.workers <= 4
    seeds = read(a.seed_file) if a.seed_file else list(modules[0]['seeds'])
    assert len(set(seeds)) == len(seeds) and set(seeds) <= set(modules[0]['seeds'])
    rows, active = [], {}
    for seed in seeds:
        # Convert and verify every saved winner before spending original-game work.
        convert(root, modules[1], seed, modules[2])
    write(root / f'execution-attempt-{a.attempt:02d}.json', {
        'workers': a.workers, 'per_seed_seconds': 900, 'seeds': seeds,
        'seed_file': str(a.seed_file) if a.seed_file else None,
        'driver_sha256': sha(__file__), 'policy_or_game_changes': False})
    remaining = iter(seeds)
    exhausted = False
    try:
        while active or not exhausted:
            while len(active) < a.workers and not exhausted:
                seed = next(remaining, None)
                if seed is None:
                    exhausted = True
                    break
                log = (root / f'seed-{seed}-attempt-{a.attempt:02d}.log').open('x')
                proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--root', str(root),
                    '--seed', str(seed), '--attempt', str(a.attempt)], stdout=log, stderr=subprocess.STDOUT)
                active[seed] = (proc, log, time.monotonic())
            for seed, (proc, log, started) in list(active.items()):
                timeout = time.monotonic() - started > 900
                if proc.poll() is None and not timeout:
                    continue
                if timeout and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill(); proc.wait()
                log.close()
                folder = root / 'original' / f'{seed}-{a.attempt:02d}'
                instance = folder / 'instance'
                if (instance / 'last-launch.json').exists():
                    modules[3].stop(instance)
                    if modules[3].instance_processes(instance):
                        modules[3].stop(instance, force=True)
                if (folder / 'result.json').exists() and proc.returncode == 0 and not timeout:
                    result = read(folder / 'result.json')
                else:
                    result = {'seed': seed, 'status': 'harness_execution_error',
                              'exit_code': proc.returncode, 'timeout': timeout}
                rows.append(result)
                del active[seed]
            summary = {'requested': len(seeds), 'completed': len(rows), 'active_workers': len(active),
                       'counts': dict(Counter(r['status'] for r in rows)), 'results': sorted(rows, key=lambda r: r['seed'])}
            write(root / f'report-attempt-{a.attempt:02d}.json', summary)
            if active:
                time.sleep(.2)
    finally:
        for seed, (proc, log, _) in active.items():
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait()
            log.close()
            instance = root / 'original' / f'{seed}-{a.attempt:02d}' / 'instance'
            if (instance / 'last-launch.json').exists():
                modules[3].stop(instance)
                if modules[3].instance_processes(instance):
                    modules[3].stop(instance, force=True)
    print(json.dumps({k: v for k, v in summary.items() if k != 'results'}), flush=True)


if __name__ == '__main__':
    main()
