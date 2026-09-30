sleep 600
while [ ! -f ~/sts/runs/c19b-c4.jsonl ] || [ $(wc -l < ~/sts/runs/c19b-c4.jsonl) -lt 740 ]; do sleep 30; done
cd ~/sts/principles/agent
~/sts/venv/bin/python p300_play_route.py ~/sts/runs/c20-rb.jsonl --arms sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+rb50f60 --first-seed 3900002000 --games 2000 --workers 58 > ~/sts/runs/c20-rb.log 2>&1
~/sts/venv/bin/python p300_play_route.py ~/sts/runs/c21-rv.jsonl --arms sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+rv50f60 --first-seed 3900002000 --games 2000 --workers 58 > ~/sts/runs/c21-rv.log 2>&1
