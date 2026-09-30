while [ ! -f ~/sts/runs/c27-fix2.jsonl ] || [ $(wc -l < ~/sts/runs/c27-fix2.jsonl) -lt 1985 ]; do sleep 30; done
cd ~/sts/principles/agent
export P300_RUNTIME=~/sts/combat4p/runtime-delivery PYTHONPATH=~/sts/principles/agent
A=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4p
~/sts/venv/bin/python p300_play_v5.py ~/sts/runs/c28-c4p.jsonl --arms $A --first-seed 3900002000 --games 2000 --workers 60 > ~/sts/runs/c28.log 2>&1
