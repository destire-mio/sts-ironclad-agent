import json,sys,math
def load(f,arm_end):
    d={}
    for l in open(f):
        r=json.loads(l)
        if r['arm'].endswith(arm_end): d[r['seed']]=r
    return d
a=load(sys.argv[1],sys.argv[2]); b=load(sys.argv[3],sys.argv[4])
s=sorted(set(a)&set(b)); n=len(s)
d=[int(b[k]['win'])-int(a[k]['win']) for k in s]
m=sum(d)/n; sd=math.sqrt(sum((x-m)**2 for x in d)/(n-1))
print(n,'base %.4f new %.4f diff %+.4f +- %.4f'%(sum(a[k]['win'] for k in s)/n,sum(b[k]['win'] for k in s)/n,m,1.96*sd/math.sqrt(n)),
 'saved',sum(x>0 for x in d),'lost',sum(x<0 for x in d),'errors',sum(bool(b[k]['error']) for k in s),
 'fixgames',sum(b[k].get('fixes',0)>0 for k in s))
for act in (2,3,4): print('reach act',act,sum(a[k]['act']>=act for k in s),sum(b[k]['act']>=act for k in s))
