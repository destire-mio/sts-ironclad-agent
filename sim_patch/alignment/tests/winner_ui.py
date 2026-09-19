"""Translate selected actions and settle native UI without choosing strategy."""


def event_action_order(game, legal_actions):
    """Simulator action bits in native enabled-button order."""
    order = tuple(legal_actions)
    screen = game.get('screen_state', {})
    if game.get('screen_type') != 'EVENT' or screen.get('event_id') != 'Vampires':
        return order
    has_vial = any(r['id'] == 'Blood Vial' for r in game['relics'])
    expected = (1, 0, 2) if has_vial else (1, 2)
    options = screen.get('options', [])
    if (len(order) != len(expected) or set(order) != set(expected)
            or len(options) != len(expected)
            or [o.get('choice_index') for o in options] != list(range(len(expected)))
            or any(o.get('disabled') for o in options)):
        raise ValueError('Vampires action/menu contract differs')
    # Native: lose max HP, then optional Blood Vial, then leave.
    # Simulator: Blood Vial=0, lose max HP=1, leave=2.
    return expected


def knowing_skull_intro(view, event_step):
    game = view['game']
    screen = game['screen_state']
    options = screen.get('options', [])
    return (event_step == 0 and game['screen_type'] == 'EVENT'
            and screen.get('event_id') == 'Knowing Skull'
            and len(options) == 1 and options[0].get('choice_index') == 0
            and not options[0].get('disabled') and 'choose' in view['available_commands'])


def dream_catcher_close(view, rewards):
    game = view['game']
    screen = game['screen_state']
    return (game['room_type'] == 'RestRoom' and game['screen_type'] == 'REST'
            and screen.get('has_rested') and screen.get('rest_options') == []
            and any(r['id'] == 'Dream Catcher' for r in game['relics'])
            and not any(rewards.values()) and 'proceed' in view['available_commands'])


def terminal_headbutt_selection(view, played_headbutt, simulator_victory):
    game = view['game']
    screen = game['screen_state']
    combat = game.get('combat_state', {})
    monsters = combat.get('monsters', [])
    alive = [m for m in monsters if m['current_hp'] > 0 or m.get('half_dead')]
    cards = screen.get('cards', [])
    return (played_headbutt and simulator_victory and game['screen_type'] == 'GRID'
            and game['room_phase'] == 'COMBAT' and screen.get('num_cards') == 1
            and not any(screen.get(k) for k in ('for_transform', 'for_upgrade',
                                               'for_purge', 'any_number', 'confirm_up', 'selected_cards'))
            and bool(cards) and 'choose' in view['available_commands']
            and sorted(c['uuid'] for c in cards) == sorted(c['uuid'] for c in combat.get('discard_pile', []))
            and any(m['id'] == 'GremlinLeader' and m['current_hp'] <= 0 for m in monsters)
            and bool(alive) and all(m['current_hp'] > 0 and not m.get('half_dead')
                and any(p['id'] == 'Minion' for p in m['powers']) for m in alive))
