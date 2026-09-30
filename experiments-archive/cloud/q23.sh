cd ~/sts/principles/agent
export P300_RUNTIME=~/sts/combat4/runtime-delivery PYTHONPATH=~/sts/principles/agent
A=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4
~/sts/venv/bin/python p300_play_route.py ~/sts/runs/c23-base3.jsonl --arms $A --first-seed 3900002000 --games 2000 --workers 60 > ~/sts/runs/c23.log 2>&1
~/sts/venv/bin/python p300_play_route.py ~/sts/runs/c24-rb.jsonl --arms $A+rb50f60 --first-seed 3900002000 --games 2000 --workers 60 > ~/sts/runs/c24-rb.log 2>&1
~/sts/venv/bin/python p300_play_route.py ~/sts/runs/c25-rv.jsonl --arms $A+rv50f60 --first-seed 3900002000 --games 2000 --workers 60 > ~/sts/runs/c25-rv.log 2>&1
