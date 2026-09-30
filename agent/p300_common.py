"""P300 shared helpers: frozen runtime loading, trajectory restore and fight simulation.

P300 is the fight-decomposition line of work: instead of learning only from the
binary Heart outcome of whole games, measure and model individual fights
(bosses first) with the production combat search, using agent/fightsim.cpp.
"""
import gzip
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The runtime directory holds the frozen parent network, its config, the Python runtime files and
# the built engine (engine/slaythespire and engine/fightsim). Create it with
# `python scripts/assemble_runtime.py`; override the location with P300_RUNTIME.
RUNTIME = Path(os.environ.get('P300_RUNTIME', ROOT / 'runtime'))
FIGHTSIM_DIR = RUNTIME / 'engine'
ENGINE = 'arena'  # search variants of the later runtime; kept for the refine check below
PYTHON = sys.executable

os.environ.setdefault('STS_LIGHTSPEED_BUILD', str(RUNTIME / 'engine'))
# fightsim first: the optimized runtime's engine dir also holds an older fightsim build.
sys.path[:0] = [str(FIGHTSIM_DIR), str(RUNTIME / 'engine'), str(RUNTIME / 'source')]

import slaythespire as sts  # noqa: E402
import heart_runtime as H  # noqa: E402
import armG_train as A  # noqa: E402
# Load fightsim by path: armG_train puts the engine dir first on sys.path, and the
# optimized runtime's engine dir holds an older fightsim build.
import importlib.util  # noqa: E402
import importlib.machinery  # noqa: E402
_fightsim_file = next(FIGHTSIM_DIR / ('fightsim' + suffix) for suffix in importlib.machinery.EXTENSION_SUFFIXES
                      if (FIGHTSIM_DIR / ('fightsim' + suffix)).exists())
_spec = importlib.util.spec_from_file_location('fightsim', _fightsim_file)
F = importlib.util.module_from_spec(_spec)
sys.modules['fightsim'] = F
_spec.loader.exec_module(F)

CONFIG = json.loads((RUNTIME / 'config.json').read_text())
_REFINER = None
_REFINER_MODE = 'refine-ten'


def resolve_refining(game, simulations, boss_multiplier):
    """GPT's refine-ten policy: keep the original answer, spend 10% of the first budget refining.
    Only available with P300_ENGINE=combat (the add-on is built against that core)."""
    global _REFINER
    if ENGINE not in ('combat', 'combat2', 'arena'):
        raise RuntimeError('refine requires P300_ENGINE=combat, combat2 or arena')
    if _REFINER is None:
        import hashlib
        addon = RUNTIME.parent / 'refiner'
        manifest = json.loads((addon / 'manifest.json').read_text())
        digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        binary = addon / manifest['module']
        if digest(sts.__file__) != manifest['engine_sha256'] or digest(binary) != manifest['module_sha256']:
            raise RuntimeError('refinement module and active engine must match the recorded build')
        spec = importlib.util.spec_from_file_location('combat_search_algorithms', binary)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _REFINER = module
        globals()['_REFINER_MODE'] = manifest.get('default_mode', 'refine-ten')
    return _REFINER.resolve(game, simulations, boss_multiplier, _REFINER_MODE, 0.)
E = sts.MonsterEncounter
HEART_FLOOR_MIN = 50


def read_run(path):
    path = Path(path)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt') as handle:
        return json.load(handle)


def battle_states(run, want=None):
    """Replay a recorded natural trajectory; yield (prefix_index, gc) at each battle start.

    `gc` is the live context: callers must use it (or F.copy_game(gc)) before
    advancing the generator. `want(gc)` filters which battles are yielded.
    Recorded actions are replayed without fingerprint checks for speed; the
    final outcome is still compared with the recording by `replay_check`.
    """
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, run['seed'], 20)
    for index, row in enumerate(run['prefix']):
        H.clock_input(gc, CONFIG)
        if row['kind'] == 'battle':
            if want is None or want(gc):
                yield index, gc
            battle = sts.BattleContext()
            battle.init(gc)
            for bits in row['actions']:
                sts.SearchAction.from_bits(bits & 0xffffffff).execute(battle)
            battle.exit_battle(gc)
        else:
            sts.GameAction(row['action'] & 0xffffffff).execute(gc)


def is_boss(gc):
    return F.is_boss(int(gc.encounter.value))


def summary(gc):
    return dict(floor=int(gc.floor_num), act=int(gc.act), hp=int(gc.cur_hp), max_hp=int(gc.max_hp),
                encounter=gc.encounter.name, deck=len(gc.deck), relics=len(gc.relics),
                potions=int(gc.potion_count))
