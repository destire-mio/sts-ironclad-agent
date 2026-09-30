cd ~/sts/principles/agent
pkill -f "q41.s""h"
pkill -f "p300_play_v2""4.py"
sleep 20
export PYTHONPATH=~/sts/principles/agent P300_RUNTIME=~/sts/combat4r/runtime-delivery
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4r+heart2+fix2+baixi+eliteseek+fix3+spear320+cardadj+fix4
~/sts/venv/bin/python p300_play_v24.py ~/sts/runs/c46-esa1off.jsonl --arms $B+esa1off+traj --record-dir ~/sts/runs/traj-c46 --first-seed 3900012000 --games 2000 --workers 27 >> ~/sts/runs/c46.log 2>&1 &
~/sts/venv/bin/python p300_play_v24.py ~/sts/runs/c47-esa1t80.jsonl --arms $B+esa1t80+traj --record-dir ~/sts/runs/traj-c47 --first-seed 3900012000 --games 2000 --workers 27 >> ~/sts/runs/c47.log 2>&1 &
wait
