while [ ! -f ~/sts/runs/c34-old.jsonl ] || [ $(wc -l < ~/sts/runs/c34-old.jsonl) -lt 1960 ]; do sleep 30; done
cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent P300_RUNTIME=~/sts/combat4p/runtime-delivery
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide
~/sts/venv/bin/python p300_play_v9.py ~/sts/runs/c35-es.jsonl --arms $B+c4p+heart2+fix2+baixi+eliteseek+traj --first-seed 3900012000 --games 2000 --workers 62 --record-dir ~/sts/runs/traj-c35 > ~/sts/runs/c35.log 2>&1
