"""Finite native battle reachability certificates, not a deployed policy.

No transposition merging, score pruning, or guessed-state equivalence is used.
A node/depth/time bound creates an unknown result, never an impossibility proof.
"""
import time


def require(condition, message):
    if not condition:
        raise ValueError(message)


def outcome(adapter, state, target_turn):
    terminal, survived = adapter.terminal(state)
    if terminal:
        return 'alive' if survived else 'dead'
    return 'alive' if adapter.turn(state) >= target_turn else 'branch'


def trace(adapter, root, actions, target_turn):
    """Check an existing legal path, stopping at the finite-horizon goal."""
    state = adapter.clone(root)
    used = []
    if outcome(adapter, state, target_turn) == 'alive':
        return dict(actions=used, state=state)
    for bits in actions:
        bits = adapter.canonical(bits)
        if outcome(adapter, state, target_turn) != 'branch':
            return None
        # A recorded native action may use a valid equivalent encoding that the
        # canonical menu does not emit (e.g. potion-discard target8191 vs6).
        # Positive witnesses use native legality; negative proofs enumerate and
        # verify the complete canonical menus below, without omitting any edge.
        if not adapter.valid(state, bits):
            return None
        adapter.execute(state, bits)
        used.append(bits)
        if outcome(adapter, state, target_turn) == 'alive':
            return dict(actions=used, state=state)
    return None


def search(adapter, root, target_turn, node_limit, depth_limit, seconds, progress=None):
    """Depth-first enumeration with an explicit, reviewable coverage tree."""
    require(node_limit > 0 and depth_limit > 0 and seconds > 0, 'invalid resource limit')
    started = time.monotonic()
    records = []
    witnesses = []
    actions_executed = 0
    bounded = False

    def make_node(state, parent, action, depth):
        status = outcome(adapter, state, target_turn)
        legal = sorted(adapter.actions(state)) if status == 'branch' else []
        require(status != 'branch' or bool(legal), 'undecided state has no native actions')
        require(len(legal) == len(set(legal)), 'native action bits duplicated')
        if status == 'branch' and depth >= depth_limit:
            status = 'depth_bound'
        record = dict(parent=parent, action=action, depth=depth, turn=adapter.turn(state),
                      hp=adapter.hp(state), status=status, menu=legal, children=[])
        records.append(record)
        return len(records)-1

    initial = adapter.clone(root)
    index = make_node(initial, -1, None, 0)
    stack = [(index, initial)]
    terminal_state = None
    while stack:
        index, state = stack[-1]
        record = records[index]
        if record['status'] == 'alive':
            chain = []
            cursor = index
            while records[cursor]['parent'] >= 0:
                chain.append(records[cursor]['action'])
                cursor = records[cursor]['parent']
            witnesses = list(reversed(chain))
            terminal_state = state
            break
        if record['status'] in ('dead', 'depth_bound'):
            bounded |= record['status'] == 'depth_bound'
            stack.pop()
            continue
        next_action = len(record['children'])
        if next_action == len(record['menu']):
            stack.pop()
            continue
        if len(records) >= node_limit or time.monotonic()-started >= seconds:
            bounded = True
            break
        bits = record['menu'][next_action]
        child = adapter.clone(state)
        adapter.execute(child, bits)
        actions_executed += 1
        child_index = make_node(child, index, bits, record['depth']+1)
        record['children'].append(child_index)
        stack.append((child_index, child))
        if progress is not None and len(records) % 4096 == 0:
            progress(dict(nodes=len(records), actions_executed=actions_executed,
                          seconds=time.monotonic()-started, target_turn=target_turn))
    verdict = 'surviving_prefix' if terminal_state is not None else 'unknown_bound' if bounded else 'closed_dead'
    return dict(verdict=verdict, target_turn=target_turn, nodes=records, actions=witnesses,
                actions_executed=actions_executed, seconds=time.monotonic()-started), terminal_state


def verify(adapter, root, result):
    """Re-enumerate every recorded menu; a missing branch invalidates a proof."""
    records = result['nodes']
    require(bool(records) and records[0]['parent'] == -1, 'missing certificate root')
    stack = [(0, adapter.clone(root))]
    seen = set()
    leaves = dict(alive=0, dead=0, depth_bound=0, incomplete=0)
    transitions = 0
    while stack:
        index, state = stack.pop()
        require(index not in seen and 0 <= index < len(records), 'invalid certificate graph')
        seen.add(index)
        record = records[index]
        status = outcome(adapter, state, result['target_turn'])
        require(record['turn'] == adapter.turn(state) and record['hp'] == adapter.hp(state),
                'certificate native state disagrees')
        if status != 'branch':
            require(record['status'] == status and not record['menu'] and not record['children'],
                    'wrong terminal classification')
            leaves[status] += 1
            continue
        legal = sorted(adapter.actions(state))
        require(bool(legal) and legal == record['menu'], 'certificate omitted a legal action')
        require(record['status'] in ('branch', 'depth_bound'), 'wrong branch classification')
        children = record['children']
        require(len(children) <= len(legal), 'too many recorded child edges')
        if record['status'] == 'depth_bound':
            require(not children, 'depth bound has children')
            leaves['depth_bound'] += 1
        elif len(children) < len(legal):
            leaves['incomplete'] += 1
        for position, child_index in reversed(list(enumerate(children))):
            require(0 < child_index < len(records), 'invalid child id')
            child_record = records[child_index]
            require(child_record['parent'] == index and child_record['action'] == legal[position]
                    and child_record['depth'] == record['depth']+1, 'bad certificate edge')
            child = adapter.clone(state)
            adapter.execute(child, legal[position])
            transitions += 1
            stack.append((child_index, child))
    require(len(seen) == len(records) and transitions == result['actions_executed'], 'disconnected nodes or wrong cost')
    if result['verdict'] == 'closed_dead':
        require(leaves['dead'] > 0 and not any(leaves[k] for k in ('alive','depth_bound','incomplete')),
                'incomplete tree cannot prove death')
    elif result['verdict'] == 'surviving_prefix':
        require(leaves['alive'] > 0 and trace(adapter, root, result['actions'], result['target_turn']) is not None,
                'missing legal survival witness')
    else:
        require(result['verdict'] == 'unknown_bound' and not leaves['alive']
                and leaves['depth_bound']+leaves['incomplete'] > 0, 'wrong unknown result')
    return dict(nodes=len(records), transitions=transitions, leaves=leaves, verdict=result['verdict'])


class Native:
    def __init__(self, sts):
        self.sts = sts

    @staticmethod
    def canonical(bits):
        return int(bits) & 0xffffffff

    @staticmethod
    def clone(state):
        return state.clone()

    @staticmethod
    def turn(state):
        return int(state.turn)

    @staticmethod
    def hp(state):
        return int(state.player.cur_hp)

    def terminal(self, state):
        o = state.outcome
        return (o != self.sts.Outcome.UNDECIDED,
                o in (self.sts.Outcome.PLAYER_VICTORY,self.sts.Outcome.PLAYER_ESCAPE) and self.hp(state)>0)

    def actions(self, state):
        return [int(a.bits) for a in self.sts.get_legal_actions(state)]

    def valid(self, state, bits):
        return self.sts.SearchAction.from_bits(bits & 0xffffffff).is_valid(state)

    def execute(self, state, bits):
        a = self.sts.SearchAction.from_bits(bits & 0xffffffff)
        require(a.is_valid(state), 'illegal native prefix action')
        a.execute(state)
