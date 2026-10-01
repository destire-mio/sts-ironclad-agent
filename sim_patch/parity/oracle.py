"""Create/own/clean up a fresh licensed original-game instance.

The installed game and local oracle are user-supplied inputs. No live player's
process is attached to or terminated. Copied probe sources are bound by hashes.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
import shutil
import signal
import subprocess
import time
import zipfile

from .core import sha256, write_json


ETHEREAL_PATCH = "basemod/patches/com/megacrit/cardcrawl/actions/common/DiscardAtEndOfTurnAction/ConsistentEtherealPatch"


def configure_reference(instance: Path, profile: str) -> dict:
    """Diagnostic change to a disposable copy, never to the installed game.

    Removing this one patch restores the original unseeded Collections.shuffle
    at this call site. Other runtime patches remain, so this is not vanilla STS.
    """
    if profile not in ("installed", "without-consistent-ethereal"):
        raise ValueError("unknown original runtime profile: " + profile)
    change = {"profile": profile, "removed_classes": []}
    if profile == "without-consistent-ethereal":
        jar = instance / "mods/BaseMod.jar"
        change["before_sha256"] = sha256(jar)
        required = {ETHEREAL_PATCH + suffix for suffix in (".class", "$1.class")}
        temporary = jar.with_suffix(".parity-tmp")
        try:
            with zipfile.ZipFile(jar) as source:
                names = {n for n in source.namelist() if n.startswith(ETHEREAL_PATCH)}
                if names != required:
                    raise ValueError("BaseMod ethereal patch classes changed; inspect before removing")
                with zipfile.ZipFile(temporary, "w") as target:
                    for item in source.infolist():
                        if item.filename not in required:
                            target.writestr(item, source.read(item.filename))
            temporary.replace(jar)
        finally:
            temporary.unlink(missing_ok=True)
        change.update(removed_classes=sorted(required), after_sha256=sha256(jar))
    return change


def wait_for_start_ready(observe, timeout_seconds):
    """A mailbox response can precede the main menu; wait for its Start command."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("original main menu did not expose start")
        view = observe(timeout_seconds=remaining)
        if 'start' in view.get('available_commands', []):
            return view
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))


class Original:
    def __init__(self, oracle_root: Path, directory: Path, repo: Path, profile: str = "installed",
                 startup_timeout_seconds: float = 300):
        self.oracle_root = oracle_root.resolve()
        self.directory = directory.resolve()
        self.repo = repo.resolve()
        self.profile = profile
        self.startup_timeout_seconds = startup_timeout_seconds
        self.instance = None
        self.rpc = []
        self.previous_signals = {}

    def __enter__(self):
        if self.directory.exists():
            raise FileExistsError("preserve previous original evidence: " + str(self.directory))
        # The existing local runner configures licensed assets and the product
        # runtime; its output root is redirected into this worktree only.
        spec = importlib.util.spec_from_file_location("parity_local_original", self.oracle_root / "run.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        Q = self.module
        Q.common.OUT = self.directory.parent
        self.directory.parent.mkdir(parents=True, exist_ok=True)
        source = self.oracle_root.parent.parent / "repair-j5/candidate/instance"
        def clone(source, target):
            subprocess.run(["/bin/cp", "-c", str(source), str(target)], check=True)
        directory, instance, manifest = Q.common.clone(self.directory.name, 18119, source=source, copy_artifact=clone)
        self.instance = instance
        try:
            reference_change = configure_reference(instance, self.profile)
            for artifact in manifest["artifacts"]:
                if artifact["file"] == "mods/BaseMod.jar":
                    mod = instance / artifact["file"]
                    artifact.update(sha256=sha256(mod), size=mod.stat().st_size)
            sources = directory / "probe-sources"
            sources.mkdir()
            hashes = {}
            for name in ("AlignmentProbe.java", "RuleProbe.java", "OutsideProbe.java", "SaveProbe.java"):
                original = self.oracle_root / name
                destination = sources / name
                shutil.copy2(original, destination)
                hashes[str(original)] = sha256(original)
            alignment = sources / "AlignmentProbe.java"
            text = alignment.read_text()
            # GameActionManager.hasControl starts true and is cleared by its
            # combat update. In a completed shop it can stay true with no work.
            # Only inventory fixtures opt into the explicit queue/effect guard;
            # notification changes CommunicationMod state, never game state.
            marker = "   && !AbstractDungeon.actionManager.hasControl\n"
            if text.count(marker) != 1:
                raise ValueError("original quiet shop observer guard changed")
            text = text.replace(marker,
                "   && (!AbstractDungeon.actionManager.hasControl || ShopContinuationProbe.quietInventoryScreen())\n")
            marker = "    observerNotifications.add(note);"
            if text.count(marker) != 1:
                raise ValueError("original shop observer notification changed")
            text = text.replace(marker,
                '    note.addProperty("has_control",AbstractDungeon.actionManager.hasControl);'
                'note.addProperty("inventory_quiet",ShopContinuationProbe.quietInventoryScreen());\n' + marker)
            marker = "  }return out;\n }\n static AbstractCard card"
            if text.count(marker) != 1:
                raise ValueError("local original observer changed; inspect view() before extending it")
            alignment.write_text(text.replace(marker,
                '   out.add("parity",ParityAudit.snapshot());\n   out.add("live_run",LiveRunState.snapshot());\n  }return out;\n }\n static AbstractCard card'))
            text = alignment.read_text()
            marker = '  else if(op.equals("fixture"))fixture(req);'
            if text.count(marker) != 1:
                raise ValueError("original RPC extension point changed")
            alignment.write_text(text.replace(marker,
                '  else if(op.equals("rng_roundtrip"))return FullRngProbe.run();\n'
                '  else if(op.equals("shared_rng_sequence"))return FullRngProbe.sharedSequence();\n'
                '  else if(op.equals("live_checkpoint"))return LiveSaveState.checkpoint();\n'
                '  else if(op.equals("live_reload"))LiveSaveState.reload();\n' + marker))
            alignment.write_text(alignment.read_text().replace(marker,
                '  else if(op.equals("live_rng_restore"))LiveSaveState.restoreEnvelope(req.getAsJsonObject("state"));\n' + marker))
            # Add an explicit starting-HP fixture option without reducing max HP.
            # This touches setup only, never an original damage/healing method.
            marker = "  AbstractDungeon.player.damagedThisCombat=0;"
            text = alignment.read_text()
            if text.count(marker) != 1:
                raise ValueError("original fixture HP insertion point changed")
            alignment.write_text(text.replace(marker,
                '  if(req.has("current_hp")){int hp=req.get("current_hp").getAsInt();'
                'if(hp<1||hp>AbstractDungeon.player.maxHealth)throw new IllegalArgumentException("current_hp outside living range");'
                'AbstractDungeon.player.currentHealth=hp;AbstractDungeon.player.isBloodied=hp<=AbstractDungeon.player.maxHealth/2f;}\n'
                + marker))
            audit = self.repo / "sim_patch/parity/java/ParityAudit.java"
            shutil.copy2(audit, sources / audit.name)
            hashes[str(audit)] = sha256(audit)
            colosseum = self.repo / "sim_patch/parity/java/ColosseumProbe.java"
            shutil.copy2(colosseum, sources / colosseum.name)
            hashes[str(colosseum)] = sha256(colosseum)
            event_entry = self.repo / "sim_patch/parity/java/EventEntryProbe.java"
            shutil.copy2(event_entry, sources / event_entry.name)
            hashes[str(event_entry)] = sha256(event_entry)
            relic_acquire = self.repo / "sim_patch/parity/java/RelicAcquireProbe.java"
            shutil.copy2(relic_acquire, sources / relic_acquire.name)
            hashes[str(relic_acquire)] = sha256(relic_acquire)
            event_rewards = self.repo / "sim_patch/parity/java/EventRewardsProbe.java"
            shutil.copy2(event_rewards, sources / event_rewards.name)
            hashes[str(event_rewards)] = sha256(event_rewards)
            treasure = self.repo / "sim_patch/parity/java/TreasureProbe.java"
            shutil.copy2(treasure, sources / treasure.name)
            hashes[str(treasure)] = sha256(treasure)
            shop_continuation = self.repo / "sim_patch/parity/java/ShopContinuationProbe.java"
            shutil.copy2(shop_continuation, sources / shop_continuation.name)
            hashes[str(shop_continuation)] = sha256(shop_continuation)
            marker = '  else if(op.equals("outside_probe"))return OutsideProbe.run(req.getAsJsonObject("spec"));'
            text = alignment.read_text()
            if text.count(marker) != 1:
                raise ValueError("original room fixture insertion point changed")
            alignment.write_text(text.replace(marker, marker
                + '\n  else if(op.equals("colosseum_fixture"))return ColosseumProbe.start(req.getAsJsonObject("spec"));'
                + '\n  else if(op.equals("event_entry_fixture"))return EventEntryProbe.start(req.getAsJsonObject("spec"));'
                + '\n  else if(op.equals("relic_acquire_fixture"))return RelicAcquireProbe.start(req.getAsJsonObject("spec"));'
                + '\n  else if(op.equals("relic_acquire_observe"))return RelicAcquireProbe.snapshot();'
                + '\n  else if(op.equals("event_rewards_fixture"))return EventRewardsProbe.start(req.getAsJsonObject("spec"));'
                + '\n  else if(op.equals("event_rewards_observe"))return EventRewardsProbe.snapshot();'
                + '\n  else if(op.equals("treasure_fixture"))return TreasureProbe.start(req.getAsJsonObject("spec"));'
                + '\n  else if(op.equals("treasure_observe"))return TreasureProbe.snapshot();'
                + '\n  else if(op.equals("shop_continuation_fixture"))return ShopContinuationProbe.start(req.getAsJsonObject("spec"));'
                + '\n  else if(op.equals("shop_continuation_observe"))return ShopContinuationProbe.snapshot();'
                + '\n  else if(op.equals("shop_continuation_advance"))return ShopContinuationProbe.advanceTo(req);'))
            rng_probe = self.repo / "sim_patch/parity/java/FullRngProbe.java"
            shutil.copy2(rng_probe, sources / rng_probe.name)
            hashes[str(rng_probe)] = sha256(rng_probe)
            live_run = self.repo / "sim_patch/parity/java/LiveRunState.java"
            shutil.copy2(live_run, sources / live_run.name)
            hashes[str(live_run)] = sha256(live_run)
            live_save = self.repo / "sim_patch/parity/java/LiveSaveState.java"
            shutil.copy2(live_save, sources / live_save.name)
            hashes[str(live_save)] = sha256(live_save)
            exporter_root = self.repo / "steam/state_export_mod/src/steamstateexport"
            (sources / "steamstateexport").mkdir()
            for exporter in sorted(exporter_root.glob("*.java")):
                hashes[str(exporter)] = sha256(exporter)
                shutil.copy2(exporter, sources / "steamstateexport" / exporter.name)
            for helper in (Path(Q.__file__), Path(Q.common.__file__), Path(inspect.getsourcefile(Q.launch))):
                hashes[str(helper)] = sha256(helper)
            classes = directory / "classes"
            classes.mkdir()
            jars = [instance / "desktop-1.0.jar", instance / "ModTheSpire.jar", *sorted((instance / "mods").glob("*.jar"))]
            compiler = Q.common.ROOT / "work/native-protocol-source/ecj-4.8.jar"
            command = [str(instance / "jre/bin/java"), "-jar", str(compiler), "-1.8", "-proc:none",
                       "-classpath", ":".join(map(str, jars)), "-d", str(classes),
                       *map(str, sorted(sources.rglob("*.java")))]
            build = subprocess.run(command, capture_output=True, text=True, timeout=120)
            (directory / "compile.log").write_text(build.stdout + build.stderr)
            if build.returncode:
                raise RuntimeError("original probe compilation failed: " + build.stdout[-2500:] + build.stderr[-2500:])
            jar = instance / "mods/AlignmentProbe.jar"
            with zipfile.ZipFile(jar, "w") as output:
                output.writestr("ModTheSpire.json", json.dumps({"modid": "alignmentprobe", "name": "Parity Audit",
                    "author_list": ["Local tests"], "description": "Original state and legal-action observation",
                    "version": "0.1.0", "sts_version": "12-18-2022", "mts_version": "3.30.3",
                    "dependencies": ["basemod", "CommunicationMod", "spirelablogic"]}))
                for path in classes.rglob("*.class"):
                    output.write(path, path.relative_to(classes).as_posix())
            manifest["enabled_mods"] = [name for name in manifest["enabled_mods"]
                                        if name not in ("acceptanceprobe", "alignmentprobe")] + ["alignmentprobe"]
            manifest["artifacts"] = [a for a in manifest["artifacts"] if a["file"] != "mods/AlignmentProbe.jar"]
            manifest["artifacts"].append({"file": "mods/AlignmentProbe.jar", "sha256": sha256(jar), "size": jar.stat().st_size})
            write_json(instance / "instance.json", manifest)
            config = instance / "home/Library/Preferences/ModTheSpire/CommunicationMod/config.properties"
            config.write_text(config.read_text().replace("runAtGameStart=true", "runAtGameStart=false"))
            self.identity = {"original_game_sha256": sha256(instance / "desktop-1.0.jar"),
                             "startup_timeout_seconds": self.startup_timeout_seconds,
                             "reference_profile": reference_change,
                             "enabled_mods": manifest["enabled_mods"],
                             "runtime_mods": {str(p.relative_to(instance)): sha256(p)
                                              for p in sorted((instance / "mods").glob("*.jar"))},
                             "source_files": hashes, "compiled_probe_sha256": sha256(jar),
                             "runner_sha256": sha256(self.oracle_root / "run.py"),
                             "copied_sources": {str(p.relative_to(sources)): sha256(p) for p in sources.rglob("*.java")},
                             "instance_manifest_sha256": sha256(instance / "instance.json"),
                             "runtime_scope": "isolated modded Java logic runtime; not a vanilla-game equivalence proof; fixed logical frames"}
            write_json(directory / "identity.json", self.identity)
            for sig in (signal.SIGTERM, signal.SIGINT):
                self.previous_signals[sig] = signal.getsignal(sig)
                signal.signal(sig, self._interrupted)
            write_json(directory / "launch.json", Q.launch(instance))
            self.probe = Q.Probe(instance)
            wait_for_start_ready(lambda **kw: self.call("observe", **kw), self.startup_timeout_seconds)
            return self
        except BaseException:
            self.close()
            raise

    def _interrupted(self, signum, frame):
        raise KeyboardInterrupt(f"original run interrupted by signal {signum}")

    def call(self, op, **arguments):
        request = {"op": op, **{k: v for k, v in arguments.items() if k != "timeout_seconds"}}
        try:
            result = self.probe.call(op, **arguments)
        except BaseException as error:
            self.rpc.append({"request": request, "response": {"ok": False, "error": repr(error)}})
            raise
        self.rpc.append({"request": request, "response": {"ok": True, "result": result}})
        return result

    def close(self):
        remaining = []
        if self.instance is not None:
            Q = self.module
            stopped = Q.stop(self.instance)
            if Q.instance_processes(self.instance):
                stopped = Q.stop(self.instance, force=True)
            remaining = Q.instance_processes(self.instance)
            write_json(self.directory / "cleanup.json", {"stop": stopped, "remaining": remaining})
            if self.rpc:
                write_json(self.directory / "observations.json.gz", self.rpc)
        for sig, handler in self.previous_signals.items():
            signal.signal(sig, handler)
        self.previous_signals.clear()
        if remaining:
            raise RuntimeError("owned original instance failed to exit; inspect cleanup.json")

    def __exit__(self, *exc):
        self.close()
