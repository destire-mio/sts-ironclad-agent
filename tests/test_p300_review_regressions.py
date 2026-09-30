"""P300 decisions and collection evidence; run with the P300 native runtime."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import p300_common as C
import p300_heart_values as H
import p300_play as P
import p300_stage_values as S


@pytest.mark.parametrize('chooser', [P.sv_choice, P.hv_choice])
def test_pending_multi_card_selection_defers_without_changing_game(chooser):
    game = C.sts.GameContext(C.sts.CharacterClass.IRONCLAD, 4, 20)
    C.H.clock_input(game, C.CONFIG)
    C.sts.GameAction(2).execute(game)  # Natural Neow remove-two option.
    assert game.screen_state == C.sts.ScreenState.CARD_SELECT
    assert game.selection_count == 2
    before = C.H.fingerprint(game)
    actions = list(C.sts.get_legal_game_actions(game))
    assert chooser(game, actions, list(range(len(actions))), .01) is None
    assert C.H.fingerprint(game) == before
    # The final pick belongs to the same multi-card operation.
    actions[5].execute(game)
    before = C.H.fingerprint(game)
    actions = list(C.sts.get_legal_game_actions(game))
    assert chooser(game, actions, list(range(len(actions))), .01) is None
    assert C.H.fingerprint(game) == before


@pytest.mark.parametrize('chooser', [P.sv_choice, P.hv_choice])
def test_card_reward_skip_keeps_its_value_and_does_not_mutate_game(chooser, monkeypatch):
    game = C.sts.GameContext(C.sts.CharacterClass.IRONCLAD, 1, 20)
    C.H.clock_input(game, C.CONFIG)
    C.sts.GameAction(0).execute(game)  # Natural Neow card reward, with its continuation.
    actions = list(C.sts.get_legal_game_actions(game))
    _, descriptors, _ = C.A.build_choices(game)
    kinds = [C.H.kind(d) for d in descriptors]
    indices = [i for i, k in enumerate(kinds) if k in (C.A.AK_REWARD_CARD, C.A.AK_REWARD_SKIP)]
    assert indices
    monkeypatch.setattr(S, 'score', lambda *args: -1.)
    monkeypatch.setattr(P, 'heart_values', lambda: {'add': {n: -1. for n in C.sts.CardId.__members__}})
    before = C.H.fingerprint(game)
    chosen = chooser(game, actions, indices, .01)
    assert kinds[chosen] == C.A.AK_REWARD_SKIP
    assert C.H.fingerprint(game) == before


@pytest.mark.parametrize('chooser', [P.sv_choice, P.hv_choice])
def test_single_upgrade_uses_values_instead_of_deferring_every_selection(chooser, monkeypatch):
    game = C.sts.GameContext(C.sts.CharacterClass.IRONCLAD, 4, 20)
    C.H.clock_input(game, C.CONFIG)
    C.sts.GameAction(0).execute(game)  # Natural Neow upgrade-one option.
    assert game.selection_count == 1
    actions = list(C.sts.get_legal_game_actions(game))
    monkeypatch.setattr(S, 'score', lambda key, act: 1. if key == 'up:BASH' else -1.)
    monkeypatch.setattr(P, 'heart_values', lambda: {'up': {'BASH': 1.}})
    before = C.H.fingerprint(game)
    chosen = chooser(game, actions, list(range(len(actions))), .01)
    assert game.selection_cards[actions[chosen].idx1].id == C.sts.CardId.BASH
    assert C.H.fingerprint(game) == before
    actions[chosen].execute(game)
    assert any(c.id == C.sts.CardId.BASH and c.upgraded for c in game.deck)


@pytest.fixture
def collection_state(tmp_path, monkeypatch):
    source = tmp_path / 'trajectory.json'
    source.write_text('{"seed":4}')
    monkeypatch.setattr(C, 'battle_states', lambda run: iter([
        (0, C.sts.GameContext(C.sts.CharacterClass.IRONCLAD, run['seed'], 20))]))
    monkeypatch.setattr(H, 'variants', lambda gc: [('base', ('hp', 1.))])
    monkeypatch.setattr(H, 'stage_states', lambda *args: [(str(source), 0)])
    monkeypatch.setattr(H, 'ProcessPoolExecutor', ThreadPoolExecutor)
    return source


@pytest.mark.parametrize('error,outcome', [('native search failed', 0), (None, 0)])
def test_failed_or_undecided_fight_has_no_training_label(collection_state, monkeypatch, error, outcome):
    monkeypatch.setattr(C.F, 'simulate', lambda *args: dict(
        error=error, outcome=outcome, win=False, hp=75, max_hp=75))
    row = H.job((str(collection_state), 0, [11], 8000))
    assert row['status'] == 'fault'
    assert row['error']
    assert 'results' not in row and 'hp_after' not in row


def invoke_collection(output, monkeypatch, *extra):
    monkeypatch.setattr(sys, 'argv', ['p300_heart_values.py', str(output), '--states', '1',
                                    '--workers', '1', *extra])
    H.main()


def test_fault_file_is_separate_from_success_data(collection_state, tmp_path, monkeypatch):
    monkeypatch.setattr(C.F, 'simulate', lambda *args: dict(
        error='native search failed', outcome=0, win=False, hp=75, max_hp=75))
    output = tmp_path / 'values.jsonl'
    with pytest.raises(RuntimeError, match='fault'):
        invoke_collection(output, monkeypatch)
    assert not output.read_text().strip()
    faults = [json.loads(line) for line in Path(str(output) + '.faults.jsonl').read_text().splitlines()]
    assert len(faults) == 1 and faults[0]['status'] == 'fault'
    assert 'results' not in faults[0]


def test_real_death_remains_a_valid_zero_label(collection_state, monkeypatch):
    monkeypatch.setattr(C.F, 'simulate', lambda *args: dict(
        error=None, outcome=int(C.sts.Outcome.PLAYER_LOSS), win=False, hp=0, max_hp=75))
    row = H.job((str(collection_state), 0, [11, 12], 8000))
    assert row['status'] == 'complete'
    assert row['results'] == {'base': 0} and row['hp_after'] == {'base': 0.}
    assert row['battle_seeds'] == [11, 12]


def test_actual_native_search_error_is_not_a_loss(collection_state, monkeypatch):
    native = C.F.simulate
    def failed_search(game, encounter, sims, multiplier, seed, hp):
        # The native zero-budget search returns an error and UNDECIDED, rather
        # than raising. Exercise the production consumer of that real result.
        return native(game, int(C.E.GREMLIN_NOB.value), 0, multiplier, seed, hp)
    monkeypatch.setattr(C.F, 'simulate', failed_search)
    row = H.job((str(collection_state), 0, [11], 8000))
    assert row['status'] == 'fault' and 'terminal plan' in row['error']
    assert 'results' not in row


def test_one_failed_state_preserves_other_states(collection_state, tmp_path, monkeypatch):
    other = tmp_path / 'other.json'; other.write_text('{"seed":5}')
    monkeypatch.setattr(H, 'stage_states', lambda *args: [(str(collection_state), 0), (str(other), 0)])
    def simulate(game, *args):
        failed = game.seed == 4
        return dict(error='failed first state' if failed else None, outcome=0 if failed else 1,
                    win=not failed, hp=30, max_hp=60)
    monkeypatch.setattr(C.F, 'simulate', simulate)
    output = tmp_path / 'values.jsonl'
    with pytest.raises(RuntimeError, match='1 collection faults'):
        invoke_collection(output, monkeypatch, '--seeds', '2', '--states', '2')
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]['path'] == str(other.resolve())
    assert rows[0]['results'] == {'base': 2}
    with pytest.raises(ValueError, match='incomplete'):
        S.load_stage(output, None)


@pytest.mark.parametrize('seeds,sims', [([], 8000), ([11], 0), ([11], -1)])
def test_invalid_collection_budget_is_rejected(collection_state, seeds, sims):
    with pytest.raises(ValueError, match='positive|nonempty'):
        H.job((str(collection_state), 0, seeds, sims))


def test_legacy_output_cannot_be_silently_resumed(collection_state, tmp_path, monkeypatch):
    output = tmp_path / 'values.jsonl'
    output.write_text(json.dumps({'path': str(collection_state), 'index': 0, 'results': {'base': 1}}) + '\n')
    before = output.read_bytes()
    with pytest.raises(ValueError, match='manifest'):
        invoke_collection(output, monkeypatch, '--seeds', '8', '--sims', '16000')
    assert output.read_bytes() == before


@pytest.mark.parametrize('change', ['seeds', 'simulations', 'engine', 'source'])
def test_resume_rejects_changed_experiment(collection_state, tmp_path, monkeypatch, change):
    monkeypatch.setattr(C.F, 'simulate', lambda *args: dict(
        error=None, outcome=int(C.sts.Outcome.PLAYER_VICTORY), win=True, hp=30, max_hp=60))
    output = tmp_path / 'values.jsonl'
    invoke_collection(output, monkeypatch, '--seeds', '2')
    before = output.read_bytes()
    extra = ['--seeds', '2']
    if change == 'seeds':
        extra = ['--seeds', '8']
    elif change == 'simulations':
        extra += ['--sims', '16000']
    elif change == 'engine':
        binary = tmp_path / 'other-engine.so'; binary.write_bytes(b'another engine')
        monkeypatch.setattr(C.sts, '__file__', str(binary))
    else:
        collection_state.write_text('{"seed":5}')
    with pytest.raises(ValueError, match='changed|differs'):
        invoke_collection(output, monkeypatch, *extra)
    assert output.read_bytes() == before


def test_identical_resume_preserves_rows_and_retries_only_faults(collection_state, tmp_path, monkeypatch):
    output = tmp_path / 'values.jsonl'
    monkeypatch.setattr(C.F, 'simulate', lambda *args: dict(
        error='native search failed', outcome=0, win=False, hp=75, max_hp=75))
    with pytest.raises(RuntimeError, match='fault'):
        invoke_collection(output, monkeypatch, '--seeds', '2')
    old_faults = Path(str(output) + '.faults.jsonl').read_bytes()
    monkeypatch.setattr(C.F, 'simulate', lambda *args: dict(
        error=None, outcome=int(C.sts.Outcome.PLAYER_VICTORY), win=True, hp=30, max_hp=60))
    invoke_collection(output, monkeypatch, '--seeds', '2')
    before = output.read_bytes()
    rows = [json.loads(line) for line in before.splitlines()]
    assert len(rows) == 1 and rows[0]['results']['base'] == 2
    assert S.load_stage(output, None)['base'] == 1.
    def forbidden(*args):
        pytest.fail('a completed matching sample was rerun')
    monkeypatch.setattr(C.F, 'simulate', forbidden)
    invoke_collection(output, monkeypatch, '--seeds', '2')
    assert output.read_bytes() == before
    assert Path(str(output) + '.faults.jsonl').read_bytes() == old_faults


def test_stage_values_use_recorded_trial_count_and_reject_faults(tmp_path):
    output = tmp_path / 'values.jsonl'
    row = {'status': 'complete', 'battle_seeds': list(range(8)),
           'results': {'base': 4, 'add:BASH': 6}, 'hp_after': {'base': .3, 'add:BASH': .4}}
    output.write_text(json.dumps(row) + '\n')
    stage = S.load_stage(output, None)
    assert stage['base'] == .5 and stage['win']['add:BASH'] == .25
    output.write_text(json.dumps(dict(row, status='fault')) + '\n')
    with pytest.raises(ValueError, match='fault|incomplete'):
        S.load_stage(output, None)
