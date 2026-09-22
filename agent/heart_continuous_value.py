"""Fixed-parent value learning and support-constrained full-run improvement."""
import math
import torch

import heart_continuous_data as C


def lambda_returns(next_action_values, terminal_return, trace_lambda):
    """Undiscounted finite decision sequence; only the last reward is nonzero."""
    C.E.require(0 <= trace_lambda <= 1 and terminal_return in (0,1), 'invalid trace return')
    C.E.require(len(next_action_values)>0, 'empty decision sequence')
    output = [0.]*len(next_action_values); output[-1] = float(terminal_return)
    for i in range(len(output)-2,-1,-1):
        output[i] = (1-trace_lambda)*float(next_action_values[i+1])+trace_lambda*output[i+1]
    return output


class ContinuousValue(torch.nn.Module):
    def __init__(self, width):
        super().__init__()
        self.input = torch.nn.Linear(width,128)
        self.tail = torch.nn.Sequential(torch.nn.SiLU(),torch.nn.Linear(128,64),
                                       torch.nn.SiLU(),torch.nn.Linear(64,1))
        torch.nn.init.zeros_(self.tail[-1].weight)
        torch.nn.init.constant_(self.tail[-1].bias,math.log(.1/.9))

    def forward(self, values):
        hidden = (torch.sparse.mm(values,self.input.weight.T)+self.input.bias
                  if values.is_sparse else self.input(values))
        return self.tail(hidden).squeeze(-1)


def select(row, logits, parent, support, spec):
    C.E.require(len(logits)==len(row['descriptors']) and 0<=parent<len(logits), 'invalid full menu')
    C.E.require(bool(torch.isfinite(torch.as_tensor(logits)).all()), 'nonfinite values')
    allowed = [i for i,d in enumerate(row['descriptors']) if i==parent or C.support_key(d,spec) in support]
    return max(allowed,key=lambda i:(float(logits[i]),i==parent,-i))


class ContinuousPolicy(torch.nn.Module):
    """Every noncombat decision is eligible; no floor or single-change cutoff."""
    def __init__(self, checkpoint, x):
        super().__init__()
        C.E.require(checkpoint['model_type']=='continuous_fixed_parent_value', 'wrong model type')
        C.E.require(checkpoint['feature_spec']==C.spec_for(x), 'full-run feature schema differs')
        self.x=x;self.spec=checkpoint['feature_spec'];self.support=set(checkpoint['support'])
        self.base=x.H.load_scorer(checkpoint['base_checkpoint']).eval()
        for p in self.base.parameters():p.requires_grad_(False)
        self.value=ContinuousValue(self.spec['width']);self.value.load_state_dict(checkpoint['value_state'])
        self.eval()

    def choose(self,gc,observation,actions,descriptors):
        parent=self.base.choose(gc,observation,actions,descriptors)
        if len(actions)==1:return parent
        row=dict(observation=self.x.R.sparse([observation[i] for i in self.spec['observations']]),
                 descriptors=[self.x.R.sparse(d) for d in descriptors])
        values=torch.zeros((len(actions),self.spec['width']))
        for i in range(len(actions)):
            sparse=C.sparse_features(row,i,self.spec)
            values[i,[j for j,_ in sparse]]=torch.tensor([v for _,v in sparse],dtype=torch.float32)
        with torch.inference_mode():logits=self.value(values).tolist()
        return select(row,logits,parent,self.support,self.spec)
