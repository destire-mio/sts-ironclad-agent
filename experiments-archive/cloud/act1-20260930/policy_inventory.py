from common import *
import inspect
x,p=P.runtime()
out=[]
while True:
 out.append(dict(type=type(p).__name__,module=type(p).__module__,source=inspect.getsource(type(p).choose),prior_strength=getattr(p,'prior_strength',None)))
 if hasattr(p,'base'):p=p.base
 elif hasattr(p,'parent'):p=p.parent
 else:break
(O/'policy-stack.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
