cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent P300_RUNTIME=~/sts/combat4r/runtime-delivery
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4r+heart2+fix2+baixi+eliteseek+fix3+spear320+cardadj+fix4
while pgrep -f "c49-teacher-mor""e.jsonl" >/dev/null; do sleep 60; done
nice -n 15 ~/sts/venv/bin/python p300_play_v21.py ~/sts/runs/c51-teacher-more.jsonl --arms $B+traj --record-dir ~/sts/runs/traj-c51 --first-seed 3900300000 --games 6000 --workers 20 >> ~/sts/runs/c51.log 2>&1
