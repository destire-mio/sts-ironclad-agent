"""Read-only score-component diagnosis on three saved E89 joint fold heads.

No optimizer, new simulation, current-study labels, or model selection. The
unchanged head must reproduce every recorded E89 validation choice and E95
fit/validation summary before the ablations are interpreted.
"""
from pathlib import Path
import argparse
import datetime
import gzip
import hashlib
import json
import os
import signal
import sys
import time


def read(path):
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def verify(root, hashes):
    for name, digest in hashes.items():
        if sha(root / name) != digest:
            raise ValueError(f"frozen input changed: {root / name}")


def decode(choices, trees, states, labels, references):
    """Independent dictionary decoder; no packed indices or training targets."""
    by_seed = {tree["seed"]: tree for tree in trees}
    originals = {ref["seed"]: int(ref["status"] == "heart_win") for ref in references}
    assert len(choices) == len(originals)
    assert {row["seed"] for row in choices} == originals.keys()
    result = []
    for row in choices:
        if row["seed"] not in by_seed:
            assert row["no_intervention"]
            target = originals[row["seed"]]
        else:
            tree = by_seed[row["seed"]]
            branch = next(b for b in tree["branches"] if b["relic_candidate"] == row["relic_candidate"])
            assert not row["no_intervention"]
            if branch["card_root"] is None:
                assert row["card"] is None
                target = branch["parent_target"]
            else:
                child = row["card"]
                assert child["root_id"] == branch["card_root"]
                state = states[child["root_id"]]
                assert state["seed"] == row["seed"]
                assert state["relic_candidate"] == branch["relic_candidate"]
                leaves = {leaf["candidate"]: leaf["target"] for leaf in labels[child["root_id"]]}
                assert set(leaves) == set(state["candidates"])
                target = leaves[child["candidate"]]
        assert target in (0, 1) and target == row["target"]
        result.append(int(target))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    registration = read(out / "registration.json")
    verify(out, registration["hashes"])
    protocol = read(out / "protocol.json")
    assert protocol["experiment"] == "E132"
    assert protocol["arm"] == "joint" and protocol["l2"] == .001
    assert protocol["modes"] == ["parent_control", "full", "static_only", "context_only"]
    assert protocol["resources"] == {"threads": 1, "max_seconds": 600, "new_mcts_calls": 0, "new_optimizer_updates": 0}
    start = time.monotonic()

    def deadline(_signum, _frame):
        raise TimeoutError("E132 read-only diagnostic exceeded its 600 second limit")

    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(protocol["resources"]["max_seconds"])
    history = Path(protocol["e95_root"])
    verify(history, protocol["e95_hashes"])
    e95_protocol = read(history / "protocol.json")
    e95_complete = read(history / "completion-verification.json")
    assert e95_complete["status"] == "complete"
    verify(history, e95_complete["hashes"])
    source = Path(e95_protocol["source"])
    verify(source, e95_protocol["source_hashes"])
    os.environ["HEART_BRANCH_RUNTIME"] = str(source)
    os.environ["ALIGNMENT_BUILD"] = str(source / "engine")
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    sys.path.insert(0, str(source))
    import heart_relic_card_experiment as E
    import heart_relic_card_readout_training as T

    torch = E.H.torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    E.S.verify_files(source)
    identity = read(source / "identity.json")
    assert sha(Path(E.R.sts.__file__)) == identity["engine_sha256"] == protocol["engine_sha256"]
    assert sha(source / "model.pt") == identity["model_sha256"] == protocol["model_sha256"]
    proof = read(source / "label-verification.json")
    assert proof["status"] == "complete" and proof["zero_faults"]
    verify(source, proof["hashes"])
    references = [r for r in read(source / "references.json") if r["split"] == "fit"]
    trees = [t for t in read(source / "trees.json.gz") if t["split"] == "fit"]
    states = {r["id"]: r for r in read(source / "roots.json.gz") if r["split"] == "fit"}
    labels = {key: value for key, value in read(source / "labels.json").items() if key in states}
    assert len(references) == protocol["fit_families"] == 1536
    rs, cs = E.L.supports(trees, states)
    data = E.L.pack(trees, states, labels, references, rs, cs)
    base = torch.load(source / "model.pt", weights_only=True, map_location="cpu")
    T.M.ReadoutPolicy(T.artifact_for(base, rs, cs, "joint", {})).training_logits(data)
    stored = read(source / "joint" / "cv-0.001.json")
    artifact = torch.load(source / "joint" / "candidate.pt", weights_only=True, map_location="cpu")
    T.same_state(E.H.load_scorer(artifact["base_checkpoint"]).state_dict(), E.H.load_scorer(base).state_dict())
    expected = next(r for r in read(history / "report.json")["results"] if r["arm"] == "joint" and r["l2"] == .001)
    results = {mode: {"folds": [], "choices": []} for mode in protocol["modes"]}

    def measures(policy, packed):
        choices = E.L.deterministic_outcomes(policy, packed)
        terminal = decode(choices, trees, states, labels, packed["references"])
        outcomes = E.B.paired_counts([int(r["status"] == "heart_win") for r in packed["references"]], terminal)
        stages = {}
        with torch.no_grad():
            scores = E.L.logits(policy, packed)
            for stage, values in zip(("relic", "card"), scores):
                group = packed[stage]
                enabled = getattr(policy, "change_" + stage)
                chosen = E.L._greedy(values, group["rows"], enabled)
                stages[stage] = {
                    "enabled": enabled, "states": len(group["rows"]),
                    "unsupported_offers": int((~group["allowed"]).sum()),
                    "changed_choices": sum(choice != int(parent) for choice, parent in zip(chosen, group["baseline"])),
                }
            stochastic = float(E.L.mean_terminal_return(policy, packed))
        return choices, {"outcomes": outcomes, "stochastic_return": stochastic, "stages": stages}

    for fold in stored["folds"]:
        number = fold["fold"]
        fit_seeds, val_seeds = set(fold["fit_seeds"]), set(fold["validation_seeds"])
        assert not fit_seeds & val_seeds
        assert fit_seeds | val_seeds == {r["seed"] for r in references}
        assert val_seeds == {r["seed"] for r in references if T.fold(r["seed"]) == number}
        train, fr, fc = T.split_data(data, fit_seeds)
        validation, _, _ = T.split_data(data, val_seeds, (fr, fc))
        saved = source / "joint" / fold["checkpoint"]
        assert sha(saved) == fold["sha256"]
        heads = torch.load(saved, weights_only=True, map_location="cpu")
        assert fr == heads["relic_support"] == fold["relic_support"]
        assert fc == heads["card_support"] == fold["card_support"]
        expected_fold = next(r for r in expected["folds"] if r["fold"] == number)
        for mode, result in results.items():
            policy = T.M.ReadoutPolicy({**T.artifact_for(base, fr, fc, "joint", artifact["provenance"]), **heads})
            with torch.no_grad():
                for stage in ("relic", "card"):
                    head = getattr(policy, stage)
                    if mode in ("parent_control", "static_only"):
                        head.weight.zero_()
                    if mode in ("parent_control", "context_only"):
                        head.static_scores.zero_()
                    assert torch.equal(head.scale, heads[stage + "_state"]["scale"])
                    if mode in ("full", "context_only"):
                        assert torch.equal(head.weight, heads[stage + "_state"]["weight"])
                    if mode in ("full", "static_only"):
                        assert torch.equal(head.static_scores, heads[stage + "_state"]["static_scores"])
            fit_choices, fit_report = measures(policy, train)
            val_choices, val_report = measures(policy, validation)
            observed = [dict(row, fold=number) for row in val_choices]
            if mode == "full":
                assert observed == [r for r in stored["choices"] if r["fold"] == number]
                for name, report in (("fit", fit_report), ("validation", val_report)):
                    assert report["outcomes"] == expected_fold[name]["outcomes"]
                    assert report["stages"] == expected_fold[name]["stages"]
                    assert abs(report["stochastic_return"] - expected_fold[name]["stochastic_return"]) < 1e-7
            if mode == "parent_control":
                for report in (fit_report, val_report):
                    assert report["outcomes"]["net_gain"] == 0
                    assert all(s["changed_choices"] == 0 for s in report["stages"].values())
            result["choices"].extend(observed)
            result["folds"].append({"fold": number, "fit": fit_report, "validation": val_report})
        print(json.dumps({"completed_fold": number, "validation_wins": {
            mode: result["folds"][-1]["validation"]["outcomes"]["candidate_wins"] for mode, result in results.items()}}), flush=True)

    baseline = [int(r["status"] == "heart_win") for r in references]
    full_by_seed = {row["seed"]: row for row in results["full"]["choices"]}
    summaries = []
    for mode, result in results.items():
        by_seed = {row["seed"]: row for row in result["choices"]}
        assert len(result["choices"]) == len(by_seed) == len(references)
        outcomes = E.B.paired_counts(baseline, [by_seed[r["seed"]]["target"] for r in references])
        versus_full = E.B.paired_counts([full_by_seed[r["seed"]]["target"] for r in references],
                                      [by_seed[r["seed"]]["target"] for r in references])
        summary = {"mode": mode, "folds": result["folds"], "out_of_fold": outcomes,
            "out_of_fold_vs_full": versus_full,
            "changed_terminal_paths_vs_full": sum(by_seed[s] != full_by_seed[s] for s in by_seed),
            "fit_family_evaluations": sum(f["fit"]["outcomes"]["assigned"] for f in result["folds"]),
            "fit_candidate_wins": sum(f["fit"]["outcomes"]["candidate_wins"] for f in result["folds"]),
            "fit_baseline_wins": sum(f["fit"]["outcomes"]["baseline_wins"] for f in result["folds"])}
        assert summary["fit_family_evaluations"] == 3072
        if mode == "full":
            assert result["choices"] == stored["choices"]
            assert outcomes == expected["out_of_fold"] == stored["outcomes"]
            assert summary["fit_candidate_wins"] == expected["fit_candidate_wins"] == 446
        summaries.append(summary)
    verify(source, e95_protocol["source_hashes"])
    verify(source, proof["hashes"])
    verify(history, protocol["e95_hashes"])
    verify(out, registration["hashes"])
    write(out / "choices.json", {mode: result["choices"] for mode, result in results.items()})
    write(out / "report.json", {
        "experiment": "E132", "status": "complete",
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "elapsed_seconds": time.monotonic() - start, "fit_families": len(references),
        "results": summaries, "unchanged_full_reproduces_e89_e95": True,
        "independent_dictionary_decoder_matches_all_outcomes": True,
        "zero_components_reproduce_parent_choices": True, "source_hashes_unchanged": True,
        "new_mcts_calls": 0, "new_optimizer_updates": 0,
        "external_heldout_or_development_evaluations": 0,
        "limits": protocol["limits"],
    })
    write(out / "completion-verification.json", {"status": "complete", "hashes": {
        name: sha(out / name) for name in ("registration.json", "protocol.json", "diagnose.py", "choices.json", "report.json")}})
    signal.alarm(0)
    print(json.dumps({"status": "complete", "report_sha256": sha(out / "report.json"),
        "summary": [{k: v for k, v in result.items() if k != "folds"} for result in summaries]}), flush=True)


if __name__ == "__main__":
    main()
