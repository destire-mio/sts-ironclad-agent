cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent P300_RUNTIME=~/sts/combat4r/runtime-delivery
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4r+heart2+fix2+baixi+eliteseek+fix3+spear320+cardadj+fix4
true
nice -n 15 ~/sts/venv/bin/python p300_play_v21.py ~/sts/runs/c52-teacher-more.jsonl --arms $B+traj --record-dir ~/sts/runs/traj-c52 --first-seed 3900400000 --games 6000 --workers 14 >> ~/sts/runs/c52.log 2>&1
