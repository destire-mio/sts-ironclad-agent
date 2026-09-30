"""Frozen public-state student and exact training-loader verification."""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import torch

CODE = Path(__file__).resolve().parent / 'student-code'
sys.path.insert(0, str(CODE))
from distill2_model import load_student
from distill2_features import public_packet, schema_from_runtime
from distill2_data import Writer, Dataset


def exact(left, right, name):
    a = np.asarray(left, dtype=np.float32)
    b = np.asarray(right, dtype=np.float32)
    if a.shape != b.shape or not np.array_equal(a.view(np.uint32), b.view(np.uint32)):
        raise ValueError('training float32 bits differ: ' + name)


class StudentPolicy:
    def __init__(self, path, x, parent):
        path = Path(path)
        freeze = json.loads(path.with_name('freeze.json').read_text())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != freeze['model_sha256']:
            raise ValueError('frozen model SHA-256 mismatch')
        self.model = load_student(path, encoder=x.A)
        if self.model.schema != schema_from_runtime(x, parent):
            raise ValueError('model feature schema differs from the live runtime')
        if self.model.schema['schema_id'] != freeze['schema_id']:
            raise ValueError('freeze schema ID mismatch')
        self.A, self.sts = x.A, x.R.sts
        self.checked = self.candidates = 0
        self.dimensions = self.model.net[0].in_features
        self.digest = hashlib.sha256()
        self.model_sha256 = digest

    @torch.inference_mode()
    def choose(self, gc):
        if self.model.training or any(p.requires_grad for p in self.model.parameters()):
            raise RuntimeError('student must stay frozen and in eval mode')
        actions = list(self.sts.get_legal_game_actions(gc))
        _, descriptors, _ = self.A.build_choices(gc)
        packet = public_packet(gc, actions, descriptors, self.model.schema, self.A)
        tensors = self.model.tensors(packet)

        # Independent extraction -> production CSR writer -> production batch.
        train_actions = list(self.sts.get_legal_game_actions(gc))
        _, train_desc, _ = self.A.build_choices(gc)
        reference = public_packet(gc, train_actions, train_desc, self.model.schema, self.A)
        if packet['bits'] != reference['bits']:
            raise ValueError('training candidate order differs')
        writer = Writer()
        writer.add(reference, seed=int(gc.seed), step=0, floor=int(gc.floor_num),
                   act=int(gc.act), type=gc.screen_state.name, label=0, recorded_label=0)
        data = Dataset.__new__(Dataset)
        data.schema = self.model.schema
        for attr, key in [('obs', 'obs'), ('desc', 'desc'), ('context', 'context')]:
            arrays = writer.sparse[key].arrays(key)
            setattr(data, attr, tuple(arrays[key+'_'+k] for k in ('ptr', 'col', 'val')))
        data.meta = {k: np.asarray(v) for k, v in writer.meta.items()}
        data.routes = np.asarray(writer.meta['routes'], dtype=np.float32)
        data.offsets = np.asarray(writer.offsets, dtype=np.int64)
        data.lengths = np.diff(data.offsets)
        trained = data.batch(np.asarray([0]), 'cpu')[0]
        for i, (a, b) in enumerate(zip(tensors, trained)):
            exact(a.numpy(), b.numpy(), 'input '+str(i))
        features = self.model.features(*tensors)
        exact(features.numpy(), self.model.features(*trained).numpy(), 'full features')
        scores = self.model(*tensors)
        if not torch.isfinite(scores).all():
            raise ValueError('student returned non-finite scores')
        chosen = self.model.choose(gc, actions, descriptors)
        if chosen != int(scores.argmax()):
            raise ValueError('student argmax contract differs')
        raw = features.contiguous().numpy().tobytes()
        self.digest.update(np.asarray(packet['bits'], dtype=np.uint32).tobytes())
        self.digest.update(raw)
        self.checked += 1
        self.candidates += len(actions)
        return actions, descriptors, chosen, dict(
            feature_check='bitwise_equal_to_training_Dataset.batch',
            feature_sha256=hashlib.sha256(raw).hexdigest(), feature_dim=self.dimensions,
            schema_id=self.model.schema['schema_id'], scores=scores.tolist())
