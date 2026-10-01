"""Freeze the current arena engine and compile the live BattleContext entry.

Run with the same Python ABI as the arena runtime. All outputs belong to a new
directory in this worktree; the source experiment and installed game are read-only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim_patch.parity.core import sha256, write_json


def prepare(arena: Path, out: Path, p300: Path | None = None) -> dict:
    import pybind11
    arena, out = arena.resolve(), out.resolve()
    if out.exists():
        raise FileExistsError(out)
    runtime = arena / "runtime"
    source = arena / "variants/arena"
    core = arena / "build/optimized-arena/libsts_core.a"
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    for name in ("slaythespire", "fightsim"):
        if not (runtime / "engine" / (name + suffix)).is_file():
            raise ValueError("Python ABI differs from the recorded arena runtime")
    # These are simulator sources, never the original game's code or assets.
    shutil.copytree(runtime, out, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(source / "include", out / "build-source/include")
    shutil.copy2(core, out / "build-source/libsts_core.a")
    source_files = sorted(source.joinpath("include").rglob("*.h"))
    native = ROOT / "steam/native"
    for file in native.iterdir():
        shutil.copy2(file, out / "build-source" / file.name)
        source_files.append(file)
    reuse_header = ROOT / "combat_engine/combat4r/agent/combat_search_reuse.h"
    shutil.copy2(reuse_header, out / "build-source/combat_search_reuse.h")
    source_files.append(reuse_header)
    binary = out / "engine" / ("live_combat_search" + suffix)
    command = ["/usr/bin/c++", "-std=c++17", "-O3", "-UNDEBUG", "-mcpu=apple-m4",
               "-arch", "arm64", "-fPIC", "-fvisibility=hidden", "-bundle",
               "-undefined", "dynamic_lookup", "-flto=full",
               "-I" + str(out / "build-source"),
               "-I" + str(out / "build-source/include"), "-I" + pybind11.get_include(),
               "-I" + sysconfig.get_paths()["include"],
               str(out / "build-source/live_combat_search.cpp"),
               str(out / "build-source/libsts_core.a"), "-o", str(binary)]
    build = subprocess.run(command, text=True, capture_output=True)
    (out / "build.log").write_text(build.stdout + build.stderr)
    if build.returncode:
        raise RuntimeError("live entry build failed; see " + str(out / "build.log"))
    manifest = {
        "arm": "sims32+boss12+rest+reuse+svsel+svcard",
        "arena_source": str(arena), "python": sys.executable, "command": command,
        "inputs": {str(p): sha256(p) for p in [core, *source_files]},
        "runtime_files": {str(p.relative_to(runtime)): sha256(p)
                          for p in runtime.rglob("*") if p.is_file() and "__pycache__" not in p.parts},
        "engine_files": {p.name: sha256(p) for p in (out / "engine").glob("*.so")},
        "scope": "same arena core and unmodified reuse search, new BattleContext entry",
    }
    if p300 is not None:
        p300 = p300.resolve()
        inputs = [p300 / "agent" / name for name in ("p300_play.py", "p300_teacher.py", "p300_stage_values.py")]
        inputs += sorted((p300 / "runs/p300-fight-decomposition").glob("d[4-8]-*.jsonl*"))
        manifest["p300_inputs"] = {}
        for path in inputs:
            target = out / "p300" / path.relative_to(p300)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            manifest["p300_inputs"][str(path)] = {"path": str(target.relative_to(out)), "sha256": sha256(target)}
    write_json(out / "live-manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--p300", type=Path)
    args = parser.parse_args()
    result = prepare(args.arena, args.out, args.p300)
    print(json.dumps({"runtime": str(args.out), "engine_files": result["engine_files"]}, indent=2))
