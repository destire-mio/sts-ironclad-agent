"""Replay the immutable E62 evidence; assert its one missing-state boundary."""
from pathlib import Path
import collections
import gzip
import hashlib
import json
import os
import subprocess
import sys

root = Path(__file__).resolve().parent
source = root / "fixtures/original-e62-boundaries.json.gz"
assert hashlib.sha256(source.read_bytes()).hexdigest() == "eda569086902eb5bc60cba65690afdd7b160abd907dd27ba96ae15d50b064f9d"
rows = json.loads(gzip.decompress(source.read_bytes()))
assert len(rows) == 12
results = []
for row in rows:
    process = subprocess.run(
        [sys.executable, str(root / "compare_sequences.py"), "--stdin-row"],
        input=json.dumps(row), text=True, capture_output=True, timeout=15, check=True,
    )
    result = json.loads(process.stdout)
    if row["spec"]["name"] == "awakened_curiosity":
        combat = row["before"]["game"]["combat_state"]
        assert combat["times_damaged"] == 2
        assert "centennial_puzzle_used" not in combat["relic_combat_state"]
        assert result["status"] == "error", result
        assert result["error"] == "Centennial Puzzle snapshot requires centennial_puzzle_used after HP loss", result
        result["status"] = "coverage_gap"
        result["missing_state"] = "centennial_puzzle_used"
        result["checked_actions"] = 0
    else:
        assert result["status"] == "passed", result
        assert result["steps"] and all(not s["differences"] for s in result["steps"]), result
    results.append(result)
counts = dict(collections.Counter(r["status"] for r in results))
assert counts == {"passed": 11, "coverage_gap": 1}, counts
destination = Path(os.environ["ALIGNMENT_REPORT_DIR"]) / "e62-snapshot-boundaries.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps({"source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "counts": counts, "results": results,
    "scope": "11 historical continuations and one explicit refusal to guess unavailable relic state"}, indent=2) + "\n")
print(counts)
