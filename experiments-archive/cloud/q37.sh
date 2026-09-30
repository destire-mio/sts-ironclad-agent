cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent P300_RUNTIME=~/sts/combat4q/runtime-delivery
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide
~/sts/venv/bin/python p300_play_v19.py ~/sts/runs/c41-decfork.jsonl --arms $B+c4q+heart2+fix2+baixi+eliteseek+fix3+decfork --first-seed 3900022000 --games 2000 --workers 58 > ~/sts/runs/c41.log 2>&1
