"""Strict comparison, evidence identity and reports. No game rules live here."""
from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any


def read_json(path: str | Path) -> Any:
    path = Path(path)
    with gzip.open(path, "rt") if path.suffix == ".gz" else path.open() as stream:
        return json.load(stream)


def write_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with gzip.open(temporary, "wt") if path.suffix == ".gz" else temporary.open("w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=None if path.suffix == ".gz" else 2,
                  allow_nan=False)
        stream.write("\n")
    temporary.replace(path)


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def pointer(parent: str, key: Any) -> str:
    return parent + "/" + str(key).replace("~", "~0").replace("/", "~1")


def differences(expected: Any, actual: Any, path: str = "") -> list[dict]:
    """Symmetric: extra simulator fields, types and list order all matter."""
    if type(expected) is not type(actual):
        return [{"path": path, "kind": "type", "original": expected, "simulator": actual}]
    if isinstance(expected, dict):
        result = []
        for key in sorted(expected.keys() | actual.keys()):
            here = pointer(path, key)
            if key not in expected:
                result.append({"path": here, "kind": "extra", "simulator": actual[key]})
            elif key not in actual:
                result.append({"path": here, "kind": "missing", "original": expected[key]})
            else:
                result.extend(differences(expected[key], actual[key], here))
        return result
    if isinstance(expected, list):
        result = []
        if len(expected) != len(actual):
            result.append({"path": path, "kind": "length", "original": len(expected),
                           "simulator": len(actual)})
        for index, (left, right) in enumerate(zip(expected, actual)):
            result.extend(differences(left, right, pointer(path, index)))
        return result
    if expected != actual:
        return [{"path": path, "kind": "value", "original": expected, "simulator": actual}]
    return []


def leaves(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, (dict, list)) and value:
        pairs = value.items() if isinstance(value, dict) else enumerate(value)
        return {p: v for key, child in pairs for p, v in leaves(child, pointer(path, key)).items()}
    return {path: value}


def field_family(path: str) -> str:
    return "/".join("*" if part.isdigit() else part for part in path.split("/"))


class Observation:
    """Every raw leaf is accounted for, even if it cannot be compared yet."""
    def __init__(self, raw: dict):
        self.raw = raw
        self.fields: dict[str, Any] = {}
        self.covered: set[str] = set()
        self.exclusions: dict[str, str] = {}
        self.gaps: list[dict] = []

    def consume(self, path: str) -> Any:
        obj = self.raw
        for component in path.strip("/").split("/"):
            component = component.replace("~1", "/").replace("~0", "~")
            obj = obj[int(component)] if isinstance(obj, list) else obj[component]
        self.covered.update(leaves(obj, path))
        return obj

    def take(self, key: str, path: str, convert=lambda value: value) -> None:
        try:
            self.fields[key] = convert(self.consume(path))
        except (KeyError, IndexError, TypeError, ValueError) as error:
            self.gaps.append({"kind": "missing_observation", "path": path, "error": str(error)})

    def audit(self) -> dict:
        raw = leaves(self.raw)
        uncovered = sorted(set(raw) - self.covered - self.exclusions.keys())
        return {"compared_leaf_count": len(self.covered),
                "uncompared_leaf_count": len(uncovered),
                "uncompared_fields": sorted({field_family(p) for p in uncovered}),
                "excluded_fields": self.exclusions, "gaps": self.gaps}


def verdict(diffs: list, gaps: list, *, error: str | None = None) -> str:
    if error is not None:
        return "execution_error"
    if diffs:
        return "mismatch"
    if gaps:
        return "coverage_gap"
    return "matched"


def summarize(cases: list[dict]) -> dict:
    counts = Counter(case["status"] for case in cases)
    # Empty, interrupted and sampled runs cannot become exhaustive certificates.
    return {"cases": len(cases), "counts": dict(sorted(counts.items())),
            "observed_comparisons_match": bool(cases) and all(
                case.get("observed_match") is True for case in cases),
            "exhaustive_parity_proven": False,
            "acceptance": "INCOMPLETE",
            "reason": "Finite recorded/live cases do not enumerate all reachable states and inputs."}


def write_report(directory: Path, report: dict) -> None:
    write_json(directory / "report.json", report)
    summary = report["summary"]
    lines = ["# 原版与模拟器差分检查", "", "验收状态：INCOMPLETE。", "",
             f"检查案例：{summary['cases']}；分类：`{json.dumps(summary['counts'], ensure_ascii=False)}`。",
             "", "通过表示被比较的字段吻合；观察缺失、适配失败和未执行分支保留为缺口。", "",
             "| 案例 | 状态 | 首个分歧 |", "|---|---|---|"]
    for case in report["results"]:
        first = case.get("first_divergence") or {}
        fields = ", ".join(d.get("path", "") for d in first.get("differences", [])[:4])
        name = case["name"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {name} | {case['status']} | {fields or case.get('error', '—')} |")
    (directory / "report.md").write_text("\n".join(lines) + "\n")
