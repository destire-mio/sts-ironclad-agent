"""Reconstruct observed battle-start choices without inferring missing rule inputs."""


def queued_actions(view):
    actions = view['live_run'].get('pending_actions')
    if actions is not None:
        # Older captures named anonymous callbacks with an empty simple name;
        # their independent audit still records the fully qualified class.
        raw = view.get('parity', {}).get('raw_state', {}).get('actions', [])
        result = []
        for index, action in enumerate(actions):
            row = dict(action)
            if 'class_full' not in row and index < len(raw):
                full = raw[index]['class']
                if full.rsplit('.', 1)[-1] == row['class'] or not row['class']:
                    row['class_full'] = full
            result.append(row)
        return result
    result = []
    for raw in view['parity']['raw_state']['actions']:
        row = {key.rsplit('.', 1)[-1]: value for key, value in raw['fields'].items()}
        row['class'] = raw['class'].rsplit('.', 1)[-1]
        row['class_full'] = raw['class']
        result.append(row)
    return result


def queued_power(comparator, view, action):
    power, target = action.get('powerToApply'), action.get('target')
    if not isinstance(power, dict) or not isinstance(target, dict):
        raise ValueError('queued ApplyPowerAction lacks original power/target export')
    if power.get('owner') != target:
        raise ValueError('queued power owner differs from its original target')
    owner = target.get('kind')
    amount = action['amount']
    if owner == 'player':
        index = -1
    elif owner == 'monster':
        monsters = view['game']['combat_state']['monsters']
        original_index = target['index']
        if not 0 <= original_index < len(monsters) or monsters[original_index]['id'] != target['id']:
            raise ValueError('queued power target identity differs from original slot')
        _, targets = comparator.bridge.canonical_monsters(monsters)
        if targets.count(original_index) != 1:
            raise ValueError('queued power target has no unique native slot')
        index = targets.index(original_index)
    else:
        raise ValueError('unsupported queued power target: ' + str(owner))
    # Startup relic powers have explicit equivalents. Refuse unknown powers;
    # mapping their visible amount alone would omit callbacks and artifact.
    player = {'Buffer', 'Intangible', 'Strength', 'Dexterity', 'Artifact', 'LoseStrength', 'Weak', 'Vulnerable', 'Frail', 'No Draw'}
    monster = {'Strength', 'Weak', 'Vulnerable', 'Poison', 'Artifact'}
    identifier = {'Weakened':'Weak', 'IntangiblePlayer':'Intangible'}.get(power.get('ID'), power.get('ID'))
    if identifier not in (player if owner == 'player' else monster):
        raise ValueError('unsupported queued original power: ' + str(power.get('ID')))
    return dict(kind='power', owner=owner, target=index, power=identifier, amount=amount,
                source_monster=action.get('source', {}).get('kind') == 'monster')


def start_selection(comparator, view):
    g, r = view['game'], view['live_run']
    screen = g['screen_type']
    if g['combat_state']['turn'] != 1:
        raise ValueError('only battle-start queues are supported')
    relics = {a['id'] for a in g['relics']}
    current = r.get('current_action', {}).get('class')
    if screen == 'CARD_REWARD' and 'Toolbox' in relics:
        if current != 'ChooseOneColorless':
            raise ValueError('not an observed Toolbox selection: ' + str(current))
        spec = dict(task='TOOLBOX', cards=[comparator.sts.CardId(comparator.bridge.card_snapshot(c)['id'])
                                         for c in g['screen_state']['cards']])
    elif screen == 'HAND_SELECT' and 'Gambling Chip' in relics and g['screen_state']['max_cards'] == 99:
        if current != 'GamblingChipAction':
            raise ValueError('not an observed Gambling Chip selection: ' + str(current))
        if g['screen_state']['selected']:
            raise ValueError('partially selected start queue')
        spec = dict(task='GAMBLING_CHIP')
    else:
        raise ValueError('unsupported pending original selection')
    queue = []
    for a in queued_actions(view):
        kind, amount = a['class'], a.get('amount', 0)
        if kind in ('WaitAction', 'EnableEndTurnButtonAction', 'RelicAboveCreatureAction'):
            continue
        if kind == 'DrawCardAction':
            queue.append(dict(kind='draw', amount=amount))
        elif kind == 'GainBlockAction':
            # Monster block is a different operation.
            if a.get('target', {}).get('kind', 'player') != 'player':
                raise ValueError('unsupported queued monster GainBlockAction')
            queue.append(dict(kind='block', amount=amount))
        elif kind == 'GainEnergyAction':
            queue.append(dict(kind='energy', amount=a['energyGain']))
        elif kind == 'ApplyPowerAction':
            queue.append(queued_power(comparator, view, a))
        elif a.get('class_full') == 'com.megacrit.cardcrawl.relics.RedSkull$1' and a.get('this$0') == 'Red Skull':
            queue.append(dict(kind='red_skull'))
        elif kind == 'GamblingChipAction':
            queue.append(dict(kind='gamble'))
        elif kind == 'MakeTempCardInDrawPileAction':
            c = a['cardToMake']
            queue.append(dict(kind='make_draw', card=comparator.sts.CardId(comparator.bridge.card_snapshot(c)['id']),
                              amount=amount, shuffle=a['randomSpot']))
        elif kind == 'DamageAllEnemiesAction':
            values = a['damage']
            if not values or len(set(values)) != 1 or a['damageType'] != 'THORNS':
                raise ValueError('unsupported queued DamageAllEnemiesAction')
            queue.append(dict(kind='damage_all', amount=values[0]))
        else:
            raise ValueError('unmapped original queued action: ' + kind)
    spec['queue'] = queue
    return spec
