"""Determinism and throughput check for the fightsim batch interface."""

import sys
import threading
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

import p300_common as C  # noqa: E402


RUNS = ROOT / "runs/p211-online-actor-critic-20260924-01/episodes/fit/monte_carlo/round-0"
TRAJECTORIES = (
    RUNS / "0-0/first-attempt.json.gz",
    RUNS / "100-1/first-attempt.json.gz",
)


def _late_state(path):
    if not path.is_file():
        pytest.fail(f"trajectory needed for fightsim integration test is missing: {path}")
    run = C.read_run(path)
    for _, game in C.battle_states(run):
        if C.summary(game)["floor"] >= 35:
            return C.F.copy_game(game)
    pytest.fail(f"trajectory did not reach a battle state at floor 35: {path}")


def _encounter(name):
    return int(getattr(C.E, name).value)


def test_batch_matches_sequential_across_encounters_and_reports_speedup():
    games = [_late_state(path) for path in TRAJECTORIES]
    encounters = (
        _encounter("THREE_CULTIST"),  # normal
        _encounter("GREMLIN_NOB"),  # elite
        _encounter("THE_HEART"),
        _encounter("AWAKENED_ONE"),
        _encounter("HEXAGHOST"),
    )
    jobs = [
        (game_index, encounter, 500, 1.0, 31001 + game_index * 100 + seed_index, 0)
        for game_index in range(len(games))
        for encounter in encounters
        for seed_index in range(4)
    ]
    assert len(jobs) == 40

    started = time.perf_counter()
    sequential = [
        C.F.simulate(games[game_index], encounter, simulations, boss_multiplier, rng_seed, hp)
        for game_index, encounter, simulations, boss_multiplier, rng_seed, hp in jobs
    ]
    sequential_seconds = time.perf_counter() - started

    started = time.perf_counter()
    batched = C.F.simulate_batch(games, jobs, threads=4)
    batch_seconds = time.perf_counter() - started

    assert batched == sequential
    speedup = sequential_seconds / batch_seconds if batch_seconds else float("inf")
    print(
        "fightsim batch: "
        f"{len(jobs)} jobs, sequential={sequential_seconds:.3f}s, "
        f"threads=4 batch={batch_seconds:.3f}s, speedup={speedup:.2f}x"
    )

    started = threading.Event()
    finished = threading.Event()
    result_holder = []
    error_holder = []

    def one_batch_call():
        started.set()
        try:
            result_holder.extend(C.F.simulate_batch(
                games, [(0, _encounter("THE_HEART"), 2000, 1.0, 32001, 0)], threads=4
            ))
        except BaseException as exc:  # surface errors from the helper thread in pytest
            error_holder.append(exc)
        finally:
            finished.set()

    caller = threading.Thread(target=one_batch_call)
    caller.start()
    assert started.wait(timeout=5)
    time.sleep(0.01)  # yield the GIL so the call thread can enter simulate_batch
    python_ticks_while_running = 0
    while not finished.is_set():
        python_ticks_while_running += 1
    caller.join()
    assert not error_holder, error_holder
    assert len(result_holder) == 1
    assert result_holder[0]["error"] is None
    assert python_ticks_while_running > 0, "simulate_batch held the GIL during C++ work"
