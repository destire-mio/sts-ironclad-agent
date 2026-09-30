"""Strength-based map overrides, independent of p300_play.

route_choice(..., params={'elite_thr': .7, 'flame_thr': .8, 'mode': 'both'})
returns an action index or None. Thresholds are probabilities; None disables
that panel (burning elites fall back to elite_thr). Reuse a per-run cache and
add its cumulative cache['sims'] to the run's combat-search accounting.

Avoidance is decided at an elite entrance. A detour must have a complete path
avoiding the rejected kind, or reach a campfire/shop BEFORE another such elite;
strength is reassessed after that resource opportunity. Both also navigates
toward a reachable elite when the parent's branch has no elite opportunity.
Such distant estimates use current resources, not predicted healing/rewards.
Parent campfire/shop choices and branches with optional elite exits are kept.

The existing Python bindings cannot set encounter/RNG/burning buffs. A small
embedded adapter is compiled once into TMPDIR, against the combat3 delivery's
manifest-verified sources/ABI. This needs its compiler, headers, pybind11 and
native-build/libsts_core.a. It changes copies only; combat search still calls
C.F.resolve_combat3. No runtime or repository file is patched.
"""
from functools import lru_cache
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile

import p300_common as C

EVAL_SEEDS = tuple(range(901, 909))
ELITES = {1: ('GREMLIN_NOB', 'LAGAVULIN', 'THREE_SENTRIES'),
          2: ('GREMLIN_LEADER', 'SLAVERS', 'BOOK_OF_STABBING'),
          3: ('GIANT_HEAD', 'NEMESIS', 'REPTOMANCER'),
          4: ('SHIELD_AND_SPEAR',)}
# Map::fromSeed draws random(0, 3): four equally likely hidden buffs.
BUFFS = (0, 1, 2, 3)

_NATIVE_SOURCE = r'''
#include <pybind11/pybind11.h>
#include "game/GameContext.h"
using namespace sts;
PYBIND11_MODULE(_route_prepare, m) {
    m.def("prepare", [](GameContext &g, int x, int y, int encounter,
                         std::uint64_t seed, int buff) {
        if (g.screenState != ScreenState::MAP_SCREEN || !g.map ||
            y <= g.curMapNodeY || y > 14 || x < 0 || x > 6 ||
            buff < -1 || buff > 3)
            throw std::invalid_argument("invalid route probe");
        // copy_game shares this pointer. Never write the source map.
        g.map = std::make_shared<Map>(*g.map);
        g.map->burningEliteX = buff < 0 ? -1 : x;
        g.map->burningEliteY = buff < 0 ? -1 : y;
        g.map->burningEliteBuff = buff < 0 ? 0 : buff;
        g.floorNum += y - g.curMapNodeY;
        g.curMapNodeX = x; g.curMapNodeY = y;
        g.lastRoom = g.curRoom; g.curRoom = Room::ELITE;
        g.curEvent = Event::INVALID;
        g.seed = seed; // fixed hypothetical world, never the real run seed
        Random r(seed + g.floorNum);
        g.aiRng = g.cardRandomRng = g.cardRng = g.eventRng = r;
        g.mathUtilRng = g.merchantRng = g.miscRng = g.monsterHpRng = r;
        g.monsterRng = g.neowRng = g.potionRng = g.relicRng = r;
        g.shuffleRng = g.treasureRng = r;
        g.info = ScreenStateInfo{};
        g.outcome = GameOutcome::UNDECIDED;
        g.skipBattles = false;
        g.resolvingEscape = false;
        g.relicsOnEnterRoom(Room::ELITE);
        g.enterBattle(static_cast<MonsterEncounter>(encounter));
        // The resolver exits the battle. Do not generate hidden future rewards
        // or invoke a callback copied from the previous treasure/event room.
        g.regainControlAction = [](GameContext &q) {
            q.screenState = ScreenState::MAP_SCREEN;
        };
    });
}
'''


@lru_cache(None)
def _native():
    """Use the delivery's exact build contract, including C++ standard library."""
    if not hasattr(C.F, 'resolve_combat3'):
        raise RuntimeError('route_rules requires a combat3 delivery via P300_RUNTIME')
    manifest_path = C.RUNTIME / 'combat3-build.json'
    manifest = json.loads(manifest_path.read_text())
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    for module in (C.sts, C.F):
        path = Path(module.__file__)
        if manifest['binaries'].get(path.name) != sha(path):
            raise RuntimeError('combat3 binary differs from its build manifest')
    # Reject ABI/header drift instead of writing into an unknown native layout.
    for name, expected in manifest['source'].items():
        if '/include/' in name and sha(name) != expected:
            raise RuntimeError('combat3 header differs from its build manifest: ' + name)
    archive = C.RUNTIME / 'native-build/libsts_core.a'
    command = manifest['api_compatibility_command']
    identity = hashlib.sha256((_NATIVE_SOURCE + manifest_path.read_text() +
                               sha(archive) + sys.version).encode()).hexdigest()[:20]
    directory = Path(tempfile.gettempdir()) / ('sts-route-' + identity)
    directory.mkdir(exist_ok=True)
    binary = directory / ('_route_prepare' + sysconfig.get_config_var('EXT_SUFFIX'))
    # Processes share only this build artifact; cache state remains per caller.
    import fcntl
    with (directory / 'build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not binary.exists():
            source = directory / 'prepare.cpp'
            source.write_text(_NATIVE_SOURCE)
            args = []
            for arg in command[:command.index('-o')]:
                if arg.endswith('.cpp'):
                    args.append(str(source))
                elif arg.endswith('.a'):
                    args.append(str(archive))
                elif not arg.startswith('-fprofile-instr-use='):
                    args.append(arg)
            temp_binary = binary.with_suffix(binary.suffix + '.tmp')
            result = subprocess.run(args + ['-o', str(temp_binary)],
                                    capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError('route adapter build failed: ' + result.stderr[-6000:])
            temp_binary.replace(binary)
    spec = importlib.util.spec_from_file_location('_route_prepare', binary)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _strength(gc, node, burning, cache, before):
    """Every hypothetical encounter/seed/buff is searched once, never best-of-N."""
    key = (before, node, burning)
    panels = cache.setdefault('_route_panels', {})
    if key in panels:
        return panels[key]['p']
    prepare = _native().prepare
    rows = []
    for name in ELITES[int(gc.act)]:
        encounter = getattr(C.sts.MonsterEncounter, name)
        for seed in EVAL_SEEDS:
            for buff in BUFFS if burning else (-1,):
                copy = C.F.copy_game(gc)
                prepare(copy, *node, int(encounter), seed, buff)
                result = C.F.resolve_combat3(copy, 32000, 12.0)
                sims = int(result['simulations'])
                cache['sims'] = cache.get('sims', 0) + sims
                if result.get('error'):
                    raise RuntimeError(str(result['error']))
                outcome = int(result['outcome'])
                # Escape is not a win: it gives no elite reward/emerald key.
                if outcome == int(C.sts.Outcome.UNDECIDED):
                    raise RuntimeError('route probe ended without a combat outcome')
                rows.append(dict(encounter=name, seed=seed, buff=buff,
                                 win=outcome == int(C.sts.Outcome.PLAYER_VICTORY),
                                 simulations=sims))
    panels[key] = dict(p=sum(r['win'] for r in rows) / len(rows), rows=rows)
    return panels[key]['p']


class _Paths:
    """Visible DAG; path masks keep key opportunities on the SAME path."""
    def __init__(self, gc):
        self.gc = gc
        self.flame = tuple(int(v) for v in gc.burning_elite[:2])
        self.rooms = {(x, y): gc.map_node_room(x, y).name
                      for y in range(15) for x in range(7)}
        self.boots = max(0, next((int(r.data) for r in getattr(gc, 'relics', ())
                                 if r.id.name == 'WING_BOOTS'), 0))
        # Instance-local memoization; a global method cache would retain every
        # live GameContext for the lifetime of a worker.
        self.children = lru_cache(None)(self.children)
        self.masks = lru_cache(None)(self.masks)
        self.elites = lru_cache(None)(self.elites)

    def start(self, cx, y):
        connected = self.gc.map_node_children(int(self.gc.cur_map_node_x), y - 1)
        spent = self.boots > 0 and y > 0 and cx not in connected
        return (cx, y, self.boots - int(spent))

    def room(self, node):
        return self.rooms[node[:2]]

    def burning(self, node):
        return node[:2] == self.flame

    def children(self, node):
        x, y, boots = node
        kids = tuple(int(k) for k in self.gc.map_node_children(x, y))
        normal = tuple((k, y + 1, boots) for k in kids)
        flights = tuple((k, y + 1, boots - 1) for k in range(7)
                        if k not in kids and self.rooms[(k, y + 1)] not in ('NONE', 'INVALID')) if boots and kids else ()
        return normal + flights

    def masks(self, node, target=None):
        bits = ((1 if self.burning(node) else 0) |
                (2 if self.room(node) == 'REST' else 0) |
                (4 if node == target else 0))
        tails = {m for child in self.children(node) for m in self.masks(child, target)}
        return frozenset(bits | m for m in (tails or {0}))

    def supports(self, node, need, target=None):
        mask = need | (4 if target is not None else 0)
        return any(m & mask == mask for m in self.masks(node, target))

    def elites(self, node):
        return frozenset(({node} if self.room(node) == 'ELITE' else set()) |
                         {e for child in self.children(node) for e in self.elites(child)})

    def escape(self, node, rejected, need):
        """Avoid rejected elites until a resource stop, with key-compatible exits."""
        @lru_cache(None)
        def visit(n, remaining):
            remaining &= ~(1 if self.burning(n) else 0)
            remaining &= ~(2 if self.room(n) == 'REST' else 0)
            if self.room(n) == 'ELITE' and self.burning(n) in rejected:
                return False
            if self.room(n) in ('REST', 'SHOP'):
                return self.supports(n, remaining)
            kids = self.children(n)
            return any(visit(k, remaining) for k in kids) if kids else not remaining
        return visit(node, need)

    def score(self, node, need):
        """Rank usable paths by resources and exits, not by mere flame reachability."""
        @lru_cache(None)
        def visit(n, remaining):
            remaining &= ~(1 if self.burning(n) else 0)
            remaining &= ~(2 if self.room(n) == 'REST' else 0)
            values = {'REST': 3.5, 'SHOP': 2.0 if self.gc.gold >= 150 else .5,
                      'TREASURE': 2., 'EVENT': 1., 'MONSTER': .5, 'ELITE': 0.}
            kids = self.children(n)
            tail = max((visit(k, remaining) for k in kids), default=-math.inf if remaining else 0.)
            return values.get(self.room(n), 0.) + tail
        return visit(node, need)


def _choose(x, gc, actions, descriptors, chosen, cache, params, before):
    mode = params.get('mode', 'avoid')
    if mode not in ('avoid', 'both'):
        raise ValueError("mode must be 'avoid' or 'both'")
    elite_thr, flame_thr = params.get('elite_thr'), params.get('flame_thr')
    for threshold in (elite_thr, flame_thr):
        if threshold is not None and not 0 <= threshold <= 1:
            raise ValueError('route thresholds must be probabilities in [0, 1] or None')
    y = int(gc.cur_map_node_y) + 1
    maps = [i for i, d in enumerate(descriptors) if x.R.kind(d) == x.A.AK_MAP]
    if chosen not in maps or len(maps) < 2 or not 0 <= y < 15:
        return None
    paths = _Paths(gc)
    nodes = {i: paths.start(int(actions[i].idx1), y) for i in maps}
    # Never discard an available last-act green key, regardless of thresholds.
    need = 0
    if int(gc.act) >= 3 and not gc.green_key and any(paths.supports(n, 1) for n in nodes.values()):
        need |= 1
    if not gc.red_key and any(paths.supports(n, need | 2) for n in nodes.values()):
        need |= 2
    allowed = [i for i in maps if paths.supports(nodes[i], need)]
    rank = lambda i: (paths.score(nodes[i], need), i == chosen, -i)
    if chosen not in allowed:
        return max(allowed, key=rank)
    if len(allowed) < 2:
        return None
    if int(gc.act) not in ELITES:
        return None
    threshold = lambda n: (flame_thr if paths.burning(n) and flame_thr is not None else elite_thr)
    strength = lambda n: _strength(gc, n[:2], paths.burning(n), cache, before)
    current = nodes[chosen]
    if paths.room(current) == 'ELITE' and threshold(current) is not None:
        if strength(current) < threshold(current):
            rejected = {paths.burning(current)}
            # Do not substitute another weak type (ordinary vs burning).
            candidates = []
            for i in allowed:
                n = nodes[i]
                if i == chosen:
                    continue
                if paths.room(n) == 'ELITE' and threshold(n) is not None:
                    if strength(n) < threshold(n):
                        rejected.add(paths.burning(n))
            for i in allowed:
                if i != chosen and paths.escape(nodes[i], frozenset(rejected), need):
                    candidates.append(i)
            return max(candidates, key=rank) if candidates else None
        return None
    if mode != 'both' or paths.room(current) in ('REST', 'SHOP', 'ELITE'):
        return None
    # Optional downstream elites are still available: keep the parent's branch
    # until the entrance decision. Do not delete campfire/shop/escape choices.
    has_future = any(paths.supports(current, need, e) for e in paths.elites(current))
    targets = [(i, e) for i in allowed if i != chosen for e in paths.elites(nodes[i])
               if (e[1] == y or not has_future) and threshold(e) is not None]
    # In both mode protect early-act green opportunity too. Require green,
    # Recall and the proposed elite to coexist along one feasible path.
    seek_need = need
    if not gc.green_key and any(paths.supports(n, need | 1) for n in nodes.values()):
        seek_need |= 1
    for i, target in sorted(targets, key=lambda pair: (pair[1][1], -rank(pair[0])[0], pair)):
        if paths.supports(nodes[i], seek_need, target) and strength(target) >= threshold(target):
            return i
    return None


def route_choice(x, gc, actions, descriptors, chosen, cache, params) -> int | None:
    """No real battle search, action execution, or real RNG mutation."""
    if gc.screen_state != x.R.sts.ScreenState.MAP_SCREEN:
        return None
    if len(actions) != len(descriptors) or not 0 <= chosen < len(actions):
        return None
    before = x.R.fingerprint(gc)
    # Native fingerprint may omit the hidden map buff. Equality is an isolation
    # assertion only; the hidden value is never an input to scoring/routing.
    map_before = tuple(gc.burning_elite)
    try:
        cache.setdefault('sims', 0)
        return _choose(x, gc, actions, descriptors, chosen, cache, params, before)
    finally:
        assert x.R.fingerprint(gc) == before, 'route_rules mutated the main game/RNG'
        assert tuple(gc.burning_elite) == map_before, 'route_rules mutated the shared map'
