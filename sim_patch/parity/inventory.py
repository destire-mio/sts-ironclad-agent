"""Source-derived coverage obligations, not inferred test-coverage claims."""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
import re

from .core import read_json, sha256, write_json


HOOKS = ("onUseCard", "onPlayCard", "onExhaust", "onCardDraw", "onAttack",
         "onAttacked", "onLoseHp", "atEndOfTurn", "onPlayerEndTurn", "atTurnStart",
         "atTurnStartPostDraw", "atBattleStart", "atBattleStartPreDraw", "onShuffle",
         "onMonsterDeath", "onVictory", "onEquip", "onUnequip", "onObtainCard")
METHOD = re.compile(r"\b(?:public|protected|private)\s+(?:static\s+|final\s+)*[\w<>\[\].]+\s+(\w+)\s*\(")
BRANCH = re.compile(r"\b(if|case|default|for|while|catch)\b|\?(?!\.)")
LEXICAL = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/')


def masked_java(source: str) -> str:
    """Preserve offsets/lines while excluding comments and string contents."""
    return LEXICAL.sub(lambda match: "".join("\n" if c == "\n" else " " for c in match[0]), source)


def source_sites(path: Path, relative: str) -> dict:
    source = path.read_text()
    masked = masked_java(source)
    methods = [{"name": m[1], "offset": m.start(), "line": source.count("\n", 0, m.start()) + 1}
               for m in METHOD.finditer(masked)]
    sites = []
    for match in BRANCH.finditer(masked):
        line = source.count("\n", 0, match.start()) + 1
        sites.append({"id": f"{relative}:{line}:{match.start()}", "line": line,
                      "kind": match[0], "status": "UNINSTRUMENTED",
                      "method_hint": next((m["name"] for m in reversed(methods)
                                           if m["offset"] < match.start()), None)})
    return {"file": relative, "sha256": sha256(path), "branch_sites": sites,
            "methods": [{k: v for k, v in m.items() if k != "offset"} for m in methods],
            "hooks": sorted({m["name"] for m in methods} & set(HOOKS))}


def build_inventory(reference: Path, source_root: Path, output: Path) -> dict:
    reference_data = read_json(reference)
    items, files, missing, changed = [], {}, [], []
    id_sources = defaultdict(list)
    # Missing source associations (potions/encounters in the old list) stay visible.
    # IDs are extracted from source constants, never from simulator support lists.
    for path in sorted(source_root.rglob("*.java")):
        relative = path.relative_to(source_root).as_posix()
        text = path.read_text()
        for match in re.finditer(r'\b(?:ID|NAME|POTION_ID)\s*=\s*"([^"\n]+)"', text):
            id_sources[match[1]].append(relative)
    for old in reference_data["items"]:
        item = {"id": old["id"], "category": old["category"], "scope": old["scope"],
                "reason": old.get("reason"), "source_files": [],
                "legacy_evidence_count": len(old.get("evidence", [])),
                "coverage": "EXCLUDED" if old["scope"] != "included" else "UNVERIFIED"}
        specified = old.get("source", {}).get("file")
        candidates = [specified] if specified else id_sources.get(old["id"], [])
        if not candidates and old["category"] == "encounters":
            candidates = ["helpers/MonsterHelper.java"]
        for relative in candidates:
            path = source_root / relative
            if not path.is_file():
                missing.append({"item": old["id"], "file": relative})
                continue
            if relative not in files:
                files[relative] = source_sites(path, relative)
            item["source_files"].append(relative)
            expected = old.get("source", {}).get("sha256")
            if expected and files[relative]["sha256"] != expected:
                changed.append({"item": old["id"], "file": relative,
                                "expected": expected, "actual": files[relative]["sha256"]})
        if not item["source_files"] and item["scope"] == "included":
            missing.append({"item": old["id"], "reason": "original_source_association_missing"})
        items.append(item)
    # Rule-bearing support code also matters. Rendering classes are not silently
    # declared irrelevant; they appear in source discovery's unclassified list.
    roots = ("actions/", "powers/", "monsters/", "random/", "neow/", "rooms/",
             "rewards/", "shop/", "saveAndContinue/", "dungeons/", "cards/AbstractCard.java",
             "cards/CardGroup.java", "core/AbstractCreature.java", "characters/AbstractPlayer.java")
    discovered = []
    for path in sorted(source_root.rglob("*.java")):
        relative = path.relative_to(source_root).as_posix()
        if relative in files:
            continue
        if any(relative.startswith(prefix) for prefix in roots):
            files[relative] = source_sites(path, relative)
        else:
            discovered.append({"file": relative, "sha256": sha256(path), "scope": "UNCLASSIFIED"})
    hook_items = defaultdict(list)
    for item in items:
        if item["scope"] != "included":
            continue
        for hook in {hook for relative in item["source_files"] for hook in files[relative]["hooks"]}:
            hook_items[hook].append(f"{item['category']}:{item['id']}")
    interactions = [{"hook": hook, "items": list(pair), "orders": [list(pair), list(reversed(pair))],
                     "coverage": "UNVERIFIED"}
                    for hook, names in sorted(hook_items.items()) for pair in combinations(sorted(set(names)), 2)]
    result = {"schema_version": 1, "scope": reference_data["scope"],
              "identity": {"reference": str(reference.resolve()), "reference_sha256": sha256(reference),
                           "source_root": str(source_root.resolve())},
              "acceptance": "INCOMPLETE", "items": items, "source_files": files,
              "missing_sources": missing, "changed_sources": changed,
              "unclassified_sources": discovered, "interaction_obligations": interactions,
              "summary": {"content_counts": dict(Counter(i["category"] for i in items)),
                          "rule_source_files": len(files),
                          "uninstrumented_branch_sites": sum(len(f["branch_sites"]) for f in files.values()),
                          "interaction_pairs": len(interactions), "unclassified_sources": len(discovered)},
              "limitations": ["Syntactic branch candidates are not executed branch coverage.",
                              "Shared-hook pairs are a lower bound; cross-hook and higher-order interactions remain open.",
                              "Legacy evidence is a locator and gives no current coverage credit."]}
    write_json(output, result)
    return result
