"""One frozen MLP; argmax over the supplied legal candidates, no overrides."""
import numpy as np
import torch
from torch import nn
from distill2_base import Student as ParentFeatures
from distill2_features import public_packet, EXTRA_NAMES, ROUTE_NAMES


class Student(ParentFeatures):
    def __init__(self, schema, width=384):
        super().__init__(schema, (width,), False)
        self.width = width
        dim = schema['base_dim'] + schema['deck_offset'] + schema['OBS_DIM']-schema['BASE_OBS_DIM']
        dim += len(EXTRA_NAMES)+3+schema['context_dim']+len(ROUTE_NAMES)
        self.net = nn.Sequential(nn.Linear(dim,width),nn.ReLU(),nn.Linear(width,1))
        self.encoder = None

    def features(self, obs, desc, extra, order, context, routes):
        base = super().features(obs,desc,extra,order)
        s = self.schema
        return torch.cat([base,obs[:,:s['deck_offset']],obs[:,s['BASE_OBS_DIM']:],
                          extra,order,context,routes],1)

    def forward(self, *tensors):
        return self.net(self.features(*tensors)).squeeze(-1)

    def warm_start(self, weights):
        h,d = weights['0.weight'].shape
        if h > self.width or d != self.schema['base_dim']:
            raise ValueError('incompatible parent architecture')
        with torch.no_grad():
            self.net[0].weight[:h].zero_()
            self.net[0].weight[:h,:d].copy_(weights['0.weight'])
            self.net[0].bias[:h].copy_(weights['0.bias'])
            self.net[2].weight.zero_()
            self.net[2].weight[:,:h].copy_(weights['2.weight'])
            self.net[2].bias.copy_(weights['2.bias'])

    def tensors(self, packet):
        n = len(packet['bits'])
        order = np.asarray([[i/32,i/max(1,n-1),n/32] for i in range(n)],dtype=np.float32)
        return [torch.as_tensor(v,dtype=torch.float32) for v in (
            np.broadcast_to(packet['observation'],(n,self.schema['OBS_DIM'])).copy(),
            packet['descriptors'],np.broadcast_to(packet['extra'],(n,len(EXTRA_NAMES))).copy(),
            order,np.broadcast_to(packet['context'],(n,self.schema['context_dim'])).copy(),packet['routes'])]

    @torch.inference_mode()
    def choose(self, gc, actions, descriptors):
        p = public_packet(gc,actions,descriptors,self.schema,self.encoder)
        scores = self(*self.tensors(p))
        if not torch.isfinite(scores).all():
            raise ValueError('non-finite student scores')
        return int(scores.argmax())


def load_student(path, encoder=None):
    b = torch.load(path, map_location='cpu', weights_only=False)
    if b.get('format') != 'distill2-v1':
        raise ValueError('not a distill2 checkpoint')
    m = Student(b['schema'],b['width'])
    m.load_state_dict(b['state'])
    m.eval().requires_grad_(False)
    m.encoder = encoder
    return m
