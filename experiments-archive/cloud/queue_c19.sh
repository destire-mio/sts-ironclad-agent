while pgrep -f c18-guide.jsonl >/dev/null && [ $(wc -l < ~/sts/runs/c18-guide.jsonl) -lt 1990 ]; do sleep 30; done
cd ~/sts/principles/agent
P300_RUNTIME=~/sts/combat4/runtime-delivery PYTHONPATH=~/sts/principles/agent ~/sts/venv/bin/python p300_play_c4.py ~/sts/runs/c19-c4.jsonl --arms sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+c4 --first-seed 3900002000 --games 2000 --workers 58 > ~/sts/runs/c19-c4.log 2>&1
