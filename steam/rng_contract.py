"""Validate the production RNG envelope without losing any 64-bit state bits."""
from __future__ import annotations

DUNGEON_STREAMS = frozenset({
    "monsterRng", "mapRng", "eventRng", "merchantRng", "cardRng",
    "treasureRng", "relicRng", "potionRng", "monsterHpRng", "aiRng",
    "shuffleRng", "cardRandomRng", "miscRng",
})
GAME_STREAMS = DUNGEON_STREAMS | {"NeowEvent.rng"}
ALL_STREAMS = GAME_STREAMS | {"MathUtils.random", "Collections.r"}
COMBAT_STREAMS = {
    "ai": "aiRng", "card_random": "cardRandomRng", "misc": "miscRng",
    "monster_hp": "monsterHpRng", "potion": "potionRng", "shuffle": "shuffleRng",
}


def _uint_string(value, bits):
    return (isinstance(value, str) and value.isascii() and value.isdecimal()
            and str(int(value)) == value and 0 <= int(value) < 1 << bits)


def validate(view: dict, *, require_oracle: bool = False) -> list[dict]:
    """Return every known contract error; missing observations never count as a match."""
    errors = []

    def error(path, reason):
        errors.append({"path": path, "reason": reason})

    game = view.get("game", {})
    envelope = game.get("full_rng_state")
    if not isinstance(envelope, dict):
        return [{"path": "/game/full_rng_state", "reason": "missing full RNG envelope"}]
    if type(envelope.get("schema_version")) is not int or envelope["schema_version"] != 1:
        error("/schema_version", "unsupported RNG schema")
    if envelope.get("complete") is not True or "error" in envelope:
        error("/complete", "exporter did not complete: " + str(envelope.get("error")))
    if envelope.get("run_seed") != str(game.get("seed")):
        error("/run_seed", "run seed differs from original observation")
    if envelope.get("floor") != game.get("floor"):
        error("/floor", "floor differs from original observation")
    streams = envelope.get("streams")
    if not isinstance(streams, dict):
        return errors + [{"path": "/streams", "reason": "missing stream object"}]
    for name in sorted(ALL_STREAMS - streams.keys()):
        error("/streams/" + name, "required stream absent")
    for name in sorted(streams.keys() - ALL_STREAMS):
        error("/streams/" + name, "unknown stream requires schema review")
    for name in sorted(ALL_STREAMS & streams.keys()):
        row = streams[name]
        path = "/streams/" + name
        if not isinstance(row, dict) or type(row.get("initialized")) is not bool:
            error(path, "explicit boolean initialization state required")
            continue
        if not row["initialized"]:
            if set(row) != {"initialized"}:
                error(path, "uninitialized RNG must not contain fabricated state")
            continue
        java = name == "Collections.r"
        algorithm, class_name = (("java_lcg48", "java.util.Random") if java else
                                 ("xorshift128plus", "com.badlogic.gdx.math.RandomXS128"))
        if row.get("algorithm") != algorithm or row.get("class") != class_name:
            error(path, "unexpected RNG implementation")
        for key in (("seed48",) if java else ("seed0", "seed1")):
            if not _uint_string(row.get(key), 48 if java else 64):
                error(path + "/" + key, "canonical unsigned decimal string required")
        if not java and row.get("seed0") == row.get("seed1") == "0":
            error(path, "invalid all-zero xorshift state")
        if name in GAME_STREAMS:
            if type(row.get("counter")) is not int or not 0 <= row["counter"] < 1 << 31:
                error(path + "/counter", "game RNG counter must be a nonnegative int32")
        elif "counter" in row:
            error(path + "/counter", "shared RNG has no game-wrapper call counter")
        gaussian = row.get("gaussian")
        if (not isinstance(gaussian, dict) or type(gaussian.get("has_cached")) is not bool
                or not _uint_string(gaussian.get("cached_double_bits"), 64)):
            error(path + "/gaussian", "missing or malformed inherited Gaussian cache")

    # Keep old BattleContext clients working, and verify both exports refer to
    # the same live object rather than independently seeded approximations.
    combat = game.get("combat_state", {}).get("rngs")
    if combat is not None:
        if set(combat) != set(COMBAT_STREAMS):
            error("/combat_state/rngs", "legacy six-stream schema changed")
        for short, name in COMBAT_STREAMS.items():
            old, new = combat.get(short), streams.get(name)
            if not old or not new or not new.get("initialized"):
                error("/combat_state/rngs/" + short, "live combat RNG missing")
                continue
            if any(str(old.get(key)) != str(new.get(key)) for key in ("counter", "seed0", "seed1")):
                error("/combat_state/rngs/" + short, "legacy and full exports disagree")

    if require_oracle:
        raw = view.get("parity", {}).get("raw_state", {}).get("rng", {})
        independent = {**view.get("rng", {}),
                       "NeowEvent.rng": raw.get("NeowEvent.rng"),
                       "MathUtils.random": raw.get("MathUtils"),
                       "Collections.r": raw.get("java_util_Collections")}
        for name in sorted(ALL_STREAMS):
            row, ref = streams.get(name), independent.get(name)
            if not isinstance(row, dict) or not isinstance(ref, dict):
                error("/oracle/" + name, "independent observation absent")
                continue
            initialized = ref.get("initialized", True)
            if row.get("initialized") is not initialized:
                error("/oracle/" + name, "initialization state disagrees")
                continue
            if not initialized:
                continue
            keys = ("seed48",) if name == "Collections.r" else ("seed0", "seed1")
            if name in GAME_STREAMS:
                keys += ("counter",)
            for key in keys:
                value = ref.get(key)
                if type(value) is not int:
                    error("/oracle/" + name + "/" + key, "independent integer absent")
                elif str(value % (1 << 64)) != str(row.get(key)):
                    error("/oracle/" + name + "/" + key, "state bits disagree with independent reader")
    return errors
