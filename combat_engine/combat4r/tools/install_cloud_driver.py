from pathlib import Path
import hashlib,json
p=Path.home()/'sts/principles/agent/p300_play_v12.py';dest=p.with_name('p300_play_v15.py');data=p.read_bytes();s=data.decode()
marker="                elif 'reuse' in features and 'c4q' in features:"
assert s.count(marker)==1 and "'c4r' in features" not in s
addition="""                elif 'reuse' in features and 'c4r' in features:
                    # combat4r: repaired mechanics and winning max-HP continuation value
                    result = C.F.resolve_combat4r(gc, 80000 if 'heart2' in features and int(gc.act) == 4 else 40000,
                                                  boss_multiplier)
"""
new=s.replace(marker,addition+marker);compile(new,str(dest),'exec')
with dest.open('x') as f:f.write(new)
assert p.read_bytes()==data and dest.read_text().replace(addition,'')==s
out=Path.home()/'sts/combat4r/evidence/cloud-driver-insertion.json'
out.write_text(json.dumps({'source':str(p),'destination':str(dest),'source_sha256':hashlib.sha256(data).hexdigest(),'destination_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'insertion':addition},indent=2))
print(dest)
