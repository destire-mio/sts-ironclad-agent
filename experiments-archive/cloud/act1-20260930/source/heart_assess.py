#!/usr/bin/env python3
"""Reconstruct fitted datasets and verify saved models against paired evaluation files."""
import argparse
import hashlib
import math
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment")
    args = parser.parse_args()
    directory = Path(args.experiment).resolve()
    os.environ["STS_LIGHTSPEED_BUILD"] = str(directory / "engine")
    sys.path.insert(0, str(directory / "source"))
    import heart_train as H
    H.torch.set_num_threads(1)
    report, config, seeds = (H.read_json(directory / name) for name in ("report.json", "config.json", "seeds.json"))
    if report["status"] != "heart_fit_complete_not_promoted":
        raise ValueError("assessment requires completed fitting and paired evaluations")
    groups, selection = {}, {}
    for split in ("train", "validation"):
        # The controller visits each split in assigned seed order and stops on
        # a completed chunk. A continuation may contain cached later seeds that
        # were not part of this fit; do not silently add those to its metrics.
        files = [directory / f"branches/{split}/{seed}.json.gz" for seed in seeds[split]]
        runs = [H.read_json(path) for path in files if path.exists()][:report["collection"][split]["seeds"]]
        assert len(runs) == report["collection"][split]["seeds"]
        assert sum(len(r.get("groups", [])) for r in runs) == report["collection"][split]["roots"]
        groups[split] = H.usable_groups(runs)
        assert len(groups[split]) == report["signal"][split + "_roots"]
        selection[split] = [{"seed": g["seed"], "fingerprint": g["fingerprint"]} for g in groups[split]]
    assert not {g["seed"] for g in groups["train"]} & {g["seed"] for g in groups["validation"]}
    H.write_json(directory / "fitted-dataset-roots.json", selection)
    result = {"experiment": str(directory), "models": {}, "final_test_used": False,
              "dataset_roots": {s: len(v) for s, v in groups.items()},
              "dataset_sha256": hashlib.sha256((directory / "fitted-dataset-roots.json").read_bytes()).hexdigest()}
    evaluation_seeds = seeds["validation"][:config["natural_eval_seeds"]]
    baseline = [H.read_json(directory / f"prefix/validation/{seed}.json.gz") for seed in evaluation_seeds]
    result["heuristic_natural"] = H.summarize(baseline)
    for name in ("small", "large"):
        model = report["models"][name]
        checkpoint = H.torch.load(model["checkpoint"], map_location="cpu", weights_only=True)
        net = H.A.Scorer(tuple(checkpoint["arch"]))
        net.load_state_dict(checkpoint["state_dict"])
        assert H.state_hash(net) == checkpoint["state_hash"] != checkpoint["initial_state_hash"]
        assert sum(p.numel() for p in net.parameters()) == model["parameters"]
        checked = {}
        for split, expected in (("train", model["train"]), ("validation", model["best_validation"])):
            actual = H.metrics(net, groups[split], "heart", config["batch_groups"])
            for key, value in actual.items():
                assert value == expected[key] or (isinstance(value, float) and
                    math.isclose(value, expected[key], rel_tol=1e-8, abs_tol=1e-10)), (name, split, key, value, expected[key])
            checked[split] = actual
        mixed = [g for g in groups["validation"] if set(g["targets"]) == {0.0, 1.0}]
        choices = []
        with H.torch.no_grad():
            for group in mixed:
                _, logits = H.group_losses(net, [group], "heart")
                selected = int(logits[0].argmax())
                choices.append({"seed": group["seed"], "fingerprint": group["fingerprint"],
                                "floor": group["floor"], "screen": group["screen"],
                                "chosen": selected, "teacher": group["chosen"], "targets": group["targets"],
                                "probabilities": logits[0].sigmoid().tolist(),
                                "chosen_wins": int(group["targets"][selected]),
                                "teacher_wins": int(group["targets"][group["chosen"]])})
        evaluations = {}
        for mode in ("full", "late"):
            paths = [directory / name / f"evaluate/{mode}/{seed}.json.gz" for seed in evaluation_seeds]
            assert all(path.exists() for path in paths), (name, mode, "incomplete paired evaluation")
            runs = [H.read_json(path) for path in paths]
            assert [r["seed"] for r in runs] == evaluation_seeds
            summary = H.summarize(runs)
            for key, value in summary.items():
                assert value == model["natural_" + mode][key]
            evaluations[mode] = {**summary, "heart_wins_per_requested_run": summary["heart_wins"] / len(evaluation_seeds),
                                 "paired_results": [{"seed": r["seed"], "baseline_status": b["status"],
                                                     "model_status": r["status"], "floor_diagnostic": r.get("floor"),
                                                     "error": r.get("error")}
                                                    for r, b in zip(runs, baseline)]}
        result["models"][name] = {"parameters": model["parameters"], "selected_epoch": checkpoint["epoch"],
                                   "updates": model["updates"], "checkpoint": model["checkpoint"],
                                   "checkpoint_sha256": hashlib.sha256(Path(model["checkpoint"]).read_bytes()).hexdigest(),
                                   "metrics_verified": checked, "mixed_validation": choices,
                                   "mixed_choices_won": sum(r["chosen_wins"] for r in choices),
                                   "mixed_teacher_won": sum(r["teacher_wins"] for r in choices),
                                   "natural": evaluations}
    result["passed"] = True
    H.write_json(directory / "assessment.json", result)
    lines = ["# 铁甲战士 A20 心脏：本轮训练结果", "",
             "范围为模拟器实验，排除棱彩碎片。战斗使用基础 2000／Boss ×3 的固定 MCTS 预算；500 个最终测试种子保持封存。", "",
             f"训练包含 {len(groups['train'])} 个决策根节点，验证包含 {len(groups['validation'])} 个。"
             "两种容量使用同一组终局标签；保存的权重、数据集合和指标核验通过。", "",
             "| 指标 | 两层 128 | 两层 512 |", "|---|---:|---:|"]
    models = [result["models"][name] for name in ("small", "large")]
    for label, values in (
            ("参数量", [str(m["parameters"]) for m in models]),
            ("心脏训练参数更新次数", [str(m["updates"]) for m in models]),
            ("选择的训练轮次", [str(m["selected_epoch"]) for m in models]),
            ("有赢有输的验证节点：模型选中获胜候选", [f"{m['mixed_choices_won']} / {len(m['mixed_validation'])}" for m in models]),
            ("相同节点：固定策略选中获胜候选", [f"{m['mixed_teacher_won']} / {len(m['mixed_validation'])}" for m in models]),
            ("自然开局，全程网络，心脏通关", [f"{m['natural']['full']['heart_wins']} / {len(evaluation_seeds)}" for m in models]),
            ("自然开局，第 25 层起使用网络，心脏通关", [f"{m['natural']['late']['heart_wins']} / {len(evaluation_seeds)}" for m in models])):
        lines.append(f"| {label} | {values[0]} | {values[1]} |")
    lines += ["", "混合节点表格使用节点计数，两个模型和固定策略的分母相同；按原始种子均衡的指标保存在 report.json 中。"
              "这些节点经过可达后期课程和成功路线扩展选择，其结果不能代表自然开局胜率。", "",
              f"固定策略在同一组 {len(evaluation_seeds)} 个自然种子上的心脏通关数为 {result['heuristic_natural']['heart_wins']}。", ""]
    for name, model in result["models"].items():
        for mode, evaluation in model["natural"].items():
            lines.append(f"- {name} / {mode} 的终局分类：{evaluation['statuses']}。")
    lines += ["", "模型处于实验状态，原版连续对照与实玩迁移验证待完成。", "",
              f"[完整核验记录]({directory / 'assessment.json'}) · [训练原始报告]({directory / 'report.json'})", ""]
    for name, model in result["models"].items():
        lines.append(f"- [{name} 心脏评分模型]({model['checkpoint']})")
    (directory / "结果解读.md").write_text("\n".join(lines) + "\n")
    print({"passed": True, "dataset_roots": result["dataset_roots"], "models": {
        name: {"parameters": row["parameters"], "mixed_choices": f"{row['mixed_choices_won']}/{len(row['mixed_validation'])}",
               "teacher_choices": f"{row['mixed_teacher_won']}/{len(row['mixed_validation'])}",
               "natural": {mode: {k: v for k, v in r.items() if k != "paired_results"}
                           for mode, r in row["natural"].items()}} for name, row in result["models"].items()}})


if __name__ == "__main__":
    main()
