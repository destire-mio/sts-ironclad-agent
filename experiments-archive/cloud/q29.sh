cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix
export P300_RUNTIME=~/sts/combat4/runtime-delivery
while [ $(wc -l < ~/sts/runs/c31-mapfork.jsonl 2>/dev/null || echo 0) -lt 1940 ]; do sleep 60; done
~/sts/venv/bin/python p300_play_v6.py ~/sts/runs/c26-heart2.jsonl --arms $B+guide+c4+heart2 --first-seed 3900002000 --games 2000 --seed-file ~/sts/runs/act4seeds.txt --workers 60 > ~/sts/runs/c26.log 2>&1
while pgrep -f "runs/c31-mapfork.jsonl" >/dev/null; do sleep 30; done
export P300_RUNTIME=~/sts/combat4p/runtime-delivery
~/sts/venv/bin/python p300_play_v6.py ~/sts/runs/c28-c4p.jsonl --arms $B+guide+c4p --first-seed 3900002000 --games 2000 --workers 60 > ~/sts/runs/c28.log 2>&1
export P300_RUNTIME=~/sts/combat4/runtime-delivery
~/sts/venv/bin/python p300_play_v6.py ~/sts/runs/c32-gr2.jsonl --arms $B+guide+c4+groute2 --first-seed 3900002000 --games 2000 --workers 60 > ~/sts/runs/c32.log 2>&1
