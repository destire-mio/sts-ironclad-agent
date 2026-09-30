cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide
export P300_RUNTIME=~/sts/combat4p/runtime-delivery
~/sts/venv/bin/python p300_play_v8.py ~/sts/runs/c33-new.jsonl --arms $B+c4p+heart2+fix2+baixi --first-seed 3900012000 --games 2000 --workers 62 > ~/sts/runs/c33.log 2>&1
export P300_RUNTIME=~/sts/combat4/runtime-delivery
~/sts/venv/bin/python p300_play_v8.py ~/sts/runs/c34-old.jsonl --arms $B+c4 --first-seed 3900012000 --games 2000 --workers 62 > ~/sts/runs/c34.log 2>&1
