cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent P300_RUNTIME=~/sts/combat4r/runtime-delivery
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide
mkdir -p ~/sts/runs/traj-c45
~/sts/venv/bin/python p300_play_v23.py ~/sts/runs/c45b-shoppot.jsonl --arms $B+c4r+heart2+fix2+baixi+eliteseek+fix3+spear320+cardadj+fix4+shoppot+traj --record-dir ~/sts/runs/traj-c45 --first-seed 3900013000 --games 1000 --workers 28 > ~/sts/runs/c45b.log 2>&1
