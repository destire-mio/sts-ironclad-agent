"""A review index that preserves findings and uncovered work without pass inflation."""
from collections import Counter, defaultdict
from pathlib import Path

from .core import field_family, read_json, sha256, summarize, write_json


def aggregate(reports: list[Path], inventory: Path, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    cases, campaigns, findings = [], [], defaultdict(list)
    gaps = Counter()
    for path in reports:
        path = path.resolve()
        report = read_json(path)
        campaigns.append({"path": str(path), "sha256": sha256(path), "summary": report["summary"]})
        for case in report["results"]:
            cases.append(case)
            gaps.update(set(case.get("gap_kinds", [])))
            family_first = {}
            for divergence in case.get("all_divergences", [case.get("first_divergence") or {}]):
                for difference in divergence.get("differences", []):
                    family = "/card_identity/*" if difference["path"].startswith("/card_identity/") else field_family(difference["path"])
                    family_first.setdefault(family, divergence)
            for family, first in family_first.items():
                findings[(case["status"], family)].append({"name": case["name"], "evidence": case.get("evidence"),
                                                          "first_divergence_of_field": first})
    coverage = read_json(inventory)
    result = {"summary": summarize(cases), "campaigns": campaigns,
        "findings": [{"status": key[0], "field_family": key[1], "cases": rows}
                     for key, rows in sorted(findings.items())],
        "gaps_by_case_count": dict(sorted(gaps.items())),
        "inventory": {"path": str(inventory.resolve()), "sha256": sha256(inventory), "scope": coverage["scope"],
                      "summary": coverage["summary"], "missing_associations": len(coverage["missing_sources"]),
                      "changed_sources": len(coverage["changed_sources"])},
        "interpretation": "Groups share an observed field, not necessarily a root cause. Missing coverage blocks acceptance."}
    write_json(directory / "index.json", result)
    lines = ["# 一致性检查索引", "", "验收状态：INCOMPLETE。", "",
             "报告列出观察差异及覆盖缺口；案例数量不能证明所有状态一致。", "",
             f"范围：{coverage['scope']}。", "",
             f"案例记录：{len(cases)}；分类：`{result['summary']['counts']}`。重复复现记录计入案例数。", "",
             "| 报告 | 案例 | 分类 |", "|---|---:|---|"]
    for campaign in campaigns:
        p = Path(campaign["path"])
        lines.append(f"| [{p.parent.name}]({p}) | {campaign['summary']['cases']} | {campaign['summary']['counts']} |")
    lines.extend(["", "差异按字段分组，不表示根因数量。", "", "| 状态 | 字段 | 案例数 | 首例证据 |",
                  "|---|---|---:|---|"])
    for finding in result["findings"]:
        example = finding["cases"][0]
        lines.append(f"| {finding['status']} | `{finding['field_family']}` | {len(finding['cases'])} | "
                     f"[{example['name']}]({example['evidence']}) |")
    lines.extend(["", f"源代码覆盖清单：[inventory]({inventory.resolve()})。",
                  f"`{coverage['summary']}`；缺少源码关联 {len(coverage['missing_sources'])} 项。", "",
                  "分支条目是源码扫描结果，执行覆盖没有被证明。原版没有导出的字段也存在未知范围。"])
    (directory / "index.md").write_text("\n".join(lines) + "\n")
    return result
