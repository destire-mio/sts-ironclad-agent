while [ $(wc -l < ~/sts/runs/c23-base3.jsonl) -lt 1985 ]; do sleep 30; done
cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix
python3 -c "
import json
s=[json.loads(l) for l in open('~/sts/runs/c23-base3.jsonl')]
open('~/sts/runs/act4seeds.txt','w').write('\n'.join(str(r['seed']) for r in s if r['act']>=4))"
export P300_RUNTIME=~/sts/combat4/runtime-delivery
~/sts/venv/bin/python p300_play_v6.py ~/sts/runs/c29-g2.jsonl --arms $B+c4+guide2 --first-seed 3900002000 --games 2000 --workers 60 > ~/sts/runs/c29.log 2>&1
~/sts/venv/bin/python p300_play_v6.py ~/sts/runs/c30-g2r.jsonl --arms $B+c4+guide2+groute2 --first-seed 3900002000 --games 2000 --workers 60 > ~/sts/runs/c30.log 2>&1
~/sts/venv/bin/python p300_play_v6.py ~/sts/runs/c26-heart2.jsonl --arms $B+guide+c4+heart2 --first-seed 3900002000 --games 2000 --seed-file ~/sts/runs/act4seeds.txt --workers 60 > ~/sts/runs/c26.log 2>&1
export P300_RUNTIME=~/sts/combat4p/runtime-delivery
~/sts/venv/bin/python p300_play_v6.py ~/sts/runs/c28-c4p.jsonl --arms $B+guide+c4p --first-seed 3900002000 --games 2000 --workers 60 > ~/sts/runs/c28.log 2>&1
