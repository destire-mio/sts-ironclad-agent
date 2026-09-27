from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import read_json


def main():
    parser = argparse.ArgumentParser(description="原版/模拟器差分验收；缺口不计为通过")
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory", help="扫描原版内容、分支和效果交互的覆盖义务")
    inv.add_argument("--reference", type=Path, required=True)
    inv.add_argument("--original-source", type=Path, required=True)
    inv.add_argument("--out", type=Path, required=True)
    summary = sub.add_parser("summary", help="汇总差异和覆盖缺口，不生成全量通过声明")
    summary.add_argument("--report", type=Path, action="append", required=True)
    summary.add_argument("--inventory", type=Path, required=True)
    summary.add_argument("--out", type=Path, required=True)
    for name in ("replay", "live", "natural", "explore", "outside", "outside-live"):
        command = sub.add_parser(name)
        command.add_argument("--engine", type=Path, required=True)
        command.add_argument("--out", type=Path, required=True)
        if name != "natural":
            command.add_argument("--case-timeout", type=float, default=20)
        if name == "replay":
            command.add_argument("--source", type=Path, action="append", required=True)
            command.add_argument("--case", type=int)
        elif name == "live":
            command.add_argument("--oracle", type=Path, required=True)
            command.add_argument("--specs", type=Path, required=True)
        elif name == "natural":
            command.add_argument("--source", type=Path, required=True)
            command.add_argument("--oracle", type=Path)
            command.add_argument("--prefix-steps", type=int)
            command.add_argument("--continue-after-mismatch", action="store_true")
        elif name == "explore":
            command.add_argument("--oracle", type=Path, required=True)
            command.add_argument("--spec", type=Path, required=True)
            command.add_argument("--depth", type=int, required=True)
            command.add_argument("--max-nodes", type=int, required=True)
        elif name == "outside":
            command.add_argument("--executable", type=Path, required=True)
            command.add_argument("--source", type=Path, action="append", required=True)
        else:
            command.add_argument("--executable", type=Path, required=True)
            command.add_argument("--oracle", type=Path, required=True)
            command.add_argument("--specs", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inventory":
        from .inventory import build_inventory
        result = build_inventory(args.reference, args.original_source, args.out)
    elif args.command == "summary":
        from .report import aggregate
        result = aggregate(args.report, args.inventory, args.out)
    else:
        from .adapter import Comparator
        from .campaign import live_cases, natural_replay, replay_files
        comparator = Comparator(args.engine, Path(__file__).resolve().parents[2])
        if args.command == "replay":
            result = replay_files(comparator, args.source, args.out, args.case, args.case_timeout)
        elif args.command == "live":
            result = live_cases(comparator, args.oracle, read_json(args.specs), args.out, args.case_timeout)
        elif args.command == "natural":
            result = natural_replay(comparator, args.source, args.out, args.oracle, args.prefix_steps,
                                    args.continue_after_mismatch)
        elif args.command == "explore":
            from .explore import explore
            result = explore(comparator, args.oracle, read_json(args.spec), args.out,
                             depth=args.depth, max_nodes=args.max_nodes, timeout=args.case_timeout)
        elif args.command == "outside":
            from .outside import outside_files
            result = outside_files(comparator, args.executable, args.source, args.out, args.case_timeout)
        else:
            from .outside import live_outside
            result = live_outside(comparator, args.oracle, args.executable, read_json(args.specs), args.out, args.case_timeout)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    # 0 = all requested comparisons matched without gaps; 1 = discrepancy/error;
    # 2 = completed investigation with coverage gaps. Empty is never successful.
    if args.command in ("inventory", "summary"):
        return 2
    statuses = {row["status"] for row in result["results"]}
    if statuses - {"matched", "coverage_gap"}:
        return 1
    return 0 if statuses == {"matched"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
