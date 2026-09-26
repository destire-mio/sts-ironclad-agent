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
RUNTIME = Path('/Users/destire/Documents/ChatGPT/sljt/sts-rl-agent-pr/runs/'
               'heart-e143-continuous-transitions-20260922-01/runtime')
PYTHON = '/Users/destire/Documents/Codex/2026-09-10/new-chat-2/outputs/spire-lab/.venv/bin/python'

os.environ.setdefault('STS_LIGHTSPEED_BUILD', str(RUNTIME / 'engine'))
sys.path[:0] = [str(RUNTIME / 'engine'), str(RUNTIME / 'source'), str(ROOT / 'build')]

import slaythespire as sts  # noqa: E402
import heart_runtime as H  # noqa: E402
import armG_train as A  # noqa: E402
import fightsim as F  # noqa: E402

CONFIG = json.loads((RUNTIME / 'config.json').read_text())
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
