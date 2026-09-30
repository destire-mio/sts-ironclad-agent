while [ $(wc -l < ~/sts/runs/c36-cardfork.jsonl) -lt 1950 ]; do sleep 30; done
cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent P300_RUNTIME=~/sts/combat4q/runtime-delivery
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide
mkdir -p ~/sts/runs/traj-c37
~/sts/venv/bin/python p300_play_v11.py ~/sts/runs/c37-c4q.jsonl --arms $B+c4q+heart2+fix2+baixi+eliteseek+traj --record-dir ~/sts/runs/traj-c37 --first-seed 3900012000 --games 2000 --workers 62 > ~/sts/runs/c37.log 2>&1
