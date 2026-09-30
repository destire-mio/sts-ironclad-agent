"""Build an isolated read-only-observation variant from a verified source tree."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

from .core import read_json, sha256, write_json


def build(source: Path, source_manifest: Path, json_include: Path, output: Path):
    manifest = read_json(source_manifest)
    expected = manifest["sources"]
    changed = [name for name, value in expected.items() if not (source / name).is_file() or sha256(source / name) != value]
    if changed:
        raise ValueError("simulator source identity changed: " + str(changed))
    output.mkdir(parents=True, exist_ok=False)
    copied = output / "source"
    for name in expected:
        destination = copied / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, destination)
    # Some includes are not CMake translation dependencies in the old manifest.
    # Copy them too and record every input, not only the legacy manifest entries.
    for folder in ("include", "bindings", "src"):
        for path in (source / folder).rglob("*"):
            if path.is_file():
                dest = copied / path.relative_to(source)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    shutil.copy2(path, dest)
    binding = copied / "bindings/slaythespire.cpp"
    text = binding.read_text()
    marker = '        .def_readonly("outcome", &BattleContext::outcome)'
    if text.count(marker) != 1:
        raise ValueError("native observation insertion point changed")
    here = Path(__file__).resolve().parent
    binding.write_text(text.replace(marker, (here / "native_audit.inc").read_text() + marker))
    inputs = output / "build-inputs"
    cmake_copy = inputs / "parity/CMakeLists.txt"
    cmake_copy.parent.mkdir(parents=True)
    shutil.copy2(here / "CMakeLists.txt", cmake_copy)
    probe_copy = inputs / "alignment/tests/outside_probe.cpp"
    probe_copy.parent.mkdir(parents=True)
    shutil.copy2(here.parent / "alignment/tests/outside_probe.cpp", probe_copy)
    shutil.copy2(here.parent / "alignment/tests/colosseum_rng_probe.cpp",
                 probe_copy.parent / "colosseum_rng_probe.cpp")
    for name in ("event_entry_probe.cpp", "event_rewards_probe.cpp", "treasure_probe.cpp", "shop_continuation_probe.cpp", "reward_observation.h", "save_entry_probe.cpp", "relic_lifecycle_probe.cpp", "relic_acquire_probe.cpp"):
        shutil.copy2(here.parent / "alignment/tests" / name, probe_copy.parent / name)
    shutil.copy2(here / "native_audit.inc", inputs / "parity/native_audit.inc")
    import pybind11
    command = ["cmake", "-S", str(cmake_copy.parent.resolve()), "-B", str(output / "build"), "-DCMAKE_BUILD_TYPE=Release",
               "-DSIM_ROOT=" + str(copied.resolve()), "-DJSON_INCLUDE=" + str(json_include.resolve()),
               "-DPython_EXECUTABLE=" + sys.executable, "-Dpybind11_DIR=" + pybind11.get_cmake_dir()]
    write_json(output / "plan.json", {"source": str(source.resolve()), "source_manifest_sha256": sha256(source_manifest),
        "observation_extension_sha256": sha256(here / "native_audit.inc"), "configure": command,
        "python": sys.version, "pybind11": pybind11.__version__,
        "build_input_hashes": {str(p.relative_to(inputs)): sha256(p) for p in inputs.rglob("*") if p.is_file()},
        "json_header_hashes": {str(p.relative_to(json_include)): sha256(p) for p in json_include.rglob("*.hpp")},
        "copied_source_hashes": {str(p.relative_to(copied)): sha256(p) for p in copied.rglob("*") if p.is_file()}})
    with (output / "build.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["cmake", "--build", str(output / "build"), "-j", "4"], stdout=log, stderr=subprocess.STDOUT, check=True)
    engine = next((output / "build").glob("slaythespire*.so"))
    write_json(output / "result.json", {"engine": str(engine.resolve()), "sha256": sha256(engine),
        "outside_probe_sha256": sha256(output / "build/outside_probe"), "plan_sha256": sha256(output / "plan.json"),
        "scope": "same rule sources with an additional read-only parity_state property; regression checks required"})
    print(engine.resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--json-include", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build(args.source, args.source_manifest, args.json_include, args.out)
