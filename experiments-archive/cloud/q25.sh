while [ ! -f ~/sts/runs/c20-rb.jsonl ] || [ $(wc -l < ~/sts/runs/c20-rb.jsonl) -lt 1985 ]; do sleep 30; done
cd ~/sts/principles/agent
export P300_RUNTIME=~/sts/combat4/runtime-delivery PYTHONPATH=~/sts/principles/agent
A=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4
~/sts/venv/bin/python p300_play_v5.py ~/sts/runs/c26-heart2.jsonl --arms $A+heart2 --first-seed 3900002000 --games 2000 --workers 60 > ~/sts/runs/c26.log 2>&1
~/sts/venv/bin/python p300_play_v5.py ~/sts/runs/c27-fix2.jsonl --arms $A+fix2 --first-seed 3900002000 --games 2000 --workers 60 > ~/sts/runs/c27.log 2>&1
