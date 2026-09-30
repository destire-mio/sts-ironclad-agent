cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent P300_RUNTIME=~/sts/combat4q/runtime-delivery
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide
~/sts/venv/bin/python p300_play_v13.py ~/sts/runs/c39-cardfork2.jsonl --arms $B+c4q+heart2+fix2+baixi+eliteseek+fix3+cardfork --first-seed 3900018000 --games 1000 --workers 62 > ~/sts/runs/c39.log 2>&1
