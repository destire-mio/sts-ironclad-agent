cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent P300_RUNTIME=~/sts/combat4r/runtime-delivery
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide
mkdir -p ~/sts/runs/traj-c43
~/sts/venv/bin/python p300_play_v21.py ~/sts/runs/c43-fresh.jsonl --arms $B+c4r+heart2+fix2+baixi+eliteseek+fix3+spear320+cardadj+fix4+traj --record-dir ~/sts/runs/traj-c43 --first-seed 3900018000 --games 1000 --workers 32 > ~/sts/runs/c43.log 2>&1
