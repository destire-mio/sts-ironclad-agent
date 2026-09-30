while [ $(wc -l < ~/sts/runs/c23-base3.jsonl) -lt 1985 ]; do sleep 30; done
cd ~/sts/principles/agent
export P300_RUNTIME=~/sts/combat3/runtime-delivery PYTHONPATH=~/sts/principles/agent
A=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide
~/sts/venv/bin/python p300_play_route.py ~/sts/runs/c22-base2.jsonl --arms $A --first-seed 3900002000 --games 2000 --workers 60 > ~/sts/runs/c22.log 2>&1
~/sts/venv/bin/python p300_play_route.py ~/sts/runs/c20-rb.jsonl --arms $A+rb50f60 --first-seed 3900002000 --games 2000 --workers 60 > ~/sts/runs/c20-rb.log 2>&1
