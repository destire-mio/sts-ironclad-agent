import importlib.util
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_exact_control as F


def run_controller(tmp_path,monkeypatch,train_clean=True):
    path=Path(os.environ.get('E156_CONTROLLER_SOURCE',str(Path(__file__).resolve().parents[1]/'docs/experiments/e156-controller.py')))
    spec=importlib.util.spec_from_file_location('controller_fixture',path)
    controller=importlib.util.module_from_spec(spec);spec.loader.exec_module(controller)
    study=tmp_path/'study';control=study/'control';control.mkdir(parents=True)
    owner=tmp_path/'owned.py';helper=tmp_path/'run_collections.py';helper.write_text('# fixture\n')
    owner.write_text('''import json
from pathlib import Path
from types import SimpleNamespace
C=SimpleNamespace(__file__=str(Path(__file__).with_name('run_collections.py')))
def run_owned(directory,command,env,budget,digest):
    name=directory.name.removesuffix('-execution')
    result=dict(exit_code=0,cleanup=dict(clean=(name!='train' or TRAIN_CLEAN)))
    (directory/'pipeline-process-exit.json').write_text(json.dumps(result))
    if name=='evaluate':
        out=directory.parent/'evaluation';out.mkdir()
        (out/'completion-verification.json').write_text(json.dumps(dict(status='complete',zero_faults=True)))
    return result
'''.replace('TRAIN_CLEAN',repr(train_clean)))
    (control/'registration.json').write_text(json.dumps(dict(owned_launcher=str(owner),hashes={})))
    (study/'registration.json').write_text('{}\n')
    controller.ROOT=control;controller.STUDY=study
    monkeypatch.setattr(F,'registered',lambda _:dict(training_timeout_seconds=1,evaluation_timeout_seconds=1))
    # The fixture does not own subprocesses; exercise actual filesystem writes
    # and both real controller stages, independently of pytest's capture mode.
    monkeypatch.setattr(controller.stat,'S_ISREG',lambda _:True)
    code=controller.main();return code,study,json.loads((control/'exit.json').read_text())


def test_train_to_evaluate_handoff_updates_status_without_retraining(tmp_path,monkeypatch):
    code,study,end=run_controller(tmp_path,monkeypatch)
    assert code==0 and end['status']=='complete',end
    assert [s['stage'] for s in end['stages']]==['train','evaluate']
    assert json.loads((study/'control/status.json').read_text())==dict(stage='evaluate',completed=['train'])


def test_unclean_training_stops_before_evaluation(tmp_path,monkeypatch):
    code,study,end=run_controller(tmp_path,monkeypatch,False)
    assert code==1 and end['status']=='stopped_with_error'
    assert [s['stage'] for s in end['stages']]==['train']
    assert not (study/'evaluate-execution').exists() and not (study/'evaluation').exists()
