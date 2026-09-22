"""Admit a complete decision stage without relabelling a cancelled joint study."""
import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('E136_STUDY'),'requires frozen completed first-card inputs')
class FirstCardReuseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ['E136_STUDY'])
        path=cls.root/'program/heart_first_card_reuse.py'
        spec=importlib.util.spec_from_file_location('e136_reuse_test',path)
        cls.F=importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.F)
        cls.E=cls.F.E; cls.plan=cls.E.read(cls.root/'protocol.json')
        cls.source=Path(cls.plan['cancelled_source']); cls.x=cls.E.load_runtime(cls.plan['runtime'])
        jobs=cls.E.read(cls.source/'data/card-jobs.json')
        cls.first=next(j for j in jobs if j['state']['split']=='fit')
        cls.jobs=[j for j in jobs if j['seed']==cls.first['seed']]

    def test_complete_menu_rejects_missing_duplicate_and_other_family(self):
        self.F.complete_menu(self.first['state'],self.jobs)
        with self.assertRaisesRegex(ValueError,'missing'): self.F.complete_menu(self.first['state'],self.jobs[:-1])
        with self.assertRaisesRegex(ValueError,'duplicate'): self.F.complete_menu(self.first['state'],self.jobs+self.jobs[:1])
        wrong=copy.deepcopy(self.jobs); wrong[0]['seed']+=1
        with self.assertRaisesRegex(ValueError,'family'): self.F.complete_menu(self.first['state'],wrong)

    def test_actual_first_card_branches_are_complete_parent_continuations(self):
        traces=[]
        for job in self.jobs:
            row=self.E.checked_branch(self.x,job)
            self.assertIn(row['target'],(0.,1.))
            traces.append(dict(path=job['output'],sha256=self.E.sha(job['output']),
                interventions=[self.E.forced(job['state'],job['candidate'])]))
        with tempfile.TemporaryDirectory() as folder:
            job=dict(seed=self.first['seed'],runtime=self.plan['runtime'],traces=traces,
                     output=str(Path(folder)/'valid.json'))
            self.E.audit_worker(job,self.x.config)
            value=self.E.read(job['output']); self.assertEqual(value['status'],'complete',value)
            self.assertEqual(len(value['entries']),len(self.jobs))

    def test_audit_rejects_wrong_intervention_and_changed_trace_hash(self):
        candidate=self.first['candidate']; state=self.first['state']
        other=next(c for c in state['candidates'] if c!=candidate)
        trace=dict(path=self.first['output'],sha256=self.E.sha(self.first['output']),
                   interventions=[self.E.forced(state,other)])
        with tempfile.TemporaryDirectory() as folder:
            job=dict(seed=self.first['seed'],runtime=self.plan['runtime'],traces=[trace],
                     output=str(Path(folder)/'wrong-choice.json'))
            self.E.audit_worker(job,self.x.config)
            self.assertEqual(self.E.read(job['output'])['status'],'audit_error')
            trace['interventions']=[self.E.forced(state,candidate)]; trace['sha256']='0'*64
            job['output']=str(Path(folder)/'wrong-hash.json'); self.E.audit_worker(job,self.x.config)
            self.assertEqual(self.E.read(job['output'])['status'],'audit_error')

    def test_cancelled_source_remains_closed_and_new_closed_study_rejects(self):
        self.assertTrue((self.source/'source-closed.json').is_file())
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'source-closed.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'closed'): self.F.prepare(root)
            self.assertFalse((root/'nodes.json').exists())


if __name__=='__main__': unittest.main()
