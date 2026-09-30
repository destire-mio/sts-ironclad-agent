"""Cloud input identity audit; never modifies source/model/table inputs."""
import hashlib
import json
from pathlib import Path

root=Path(__file__).resolve().parent
runtime='~/sts/combat4/runtime-delivery/'
agent='~/sts/principles/agent/'
critical_names={'p300_common.py','p300_teacher.py','heart_early_card_scope.py',
                'guide_rules.py','p300_stage_values.py','relic_u.json'}


def digest(path):
    path=Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main():
    before=json.loads((root/'manifest.before.json').read_text())
    changes={p:dict(before=h,after=digest(p)) for p,h in before.items() if digest(p)!=h}
    critical={p:v for p,v in changes.items() if p.startswith(runtime) or
              (p.startswith(agent) and Path(p).name in critical_names) or
              Path(p).parent==root}
    stage_before=json.loads((root/'stage_tables.before.json').read_text())
    stage_changes={p:dict(before=h,after=digest(p)) for p,h in stage_before.items() if digest(p)!=h}
    result=dict(critical_changed=critical,stage_changed=stage_changes,
                other_agent_source_changed={p:v for p,v in changes.items() if p not in critical},
                runtime_and_source_files_checked=len(before),stage_files_checked=len(stage_before),
                collector_sha256=digest(root/'p300_baixi_collect.py'),
                baseline_snapshot_sha256=digest(root/'c23-base3.snapshot.jsonl'),
                rules_sha256=digest(root/'baixi_rules.py'))
    (root/'input_check.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
    assert not critical and not stage_changes,'loaded input identity needs investigation'


if __name__=='__main__':main()
