while [ ! -f ~/sts/runs/c35-es.jsonl ] || [ $(wc -l < ~/sts/runs/c35-es.jsonl) -lt 1960 ]; do sleep 30; done
cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent P300_RUNTIME=~/sts/combat4p/runtime-delivery
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide
~/sts/venv/bin/python p300_play_v10.py ~/sts/runs/c36-cardfork.jsonl --arms $B+c4p+heart2+fix2+baixi+cardfork --first-seed 3900014000 --games 2000 --workers 62 > ~/sts/runs/c36.log 2>&1
