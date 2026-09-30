while [ ! -f ~/sts/runs/c37-c4q.jsonl ] || [ $(wc -l < ~/sts/runs/c37-c4q.jsonl) -lt 1960 ]; do sleep 30; done
cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent P300_RUNTIME=~/sts/combat4q/runtime-delivery
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide
mkdir -p ~/sts/runs/traj-c38
~/sts/venv/bin/python p300_play_v12.py ~/sts/runs/c38-fix3.jsonl --arms $B+c4q+heart2+fix2+baixi+eliteseek+fix3+traj --record-dir ~/sts/runs/traj-c38 --first-seed 3900012000 --games 1000 --workers 62 > ~/sts/runs/c38.log 2>&1
