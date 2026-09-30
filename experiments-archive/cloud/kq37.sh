pkill -f "bash ~/sts/runs/q37.sh"
pkill -f c41-decfork.jsonl
sleep 5
cd ~/sts/principles/agent
python3 - <<'PY'
s = open("p300_play_v19.py").read()
a = "                    and decfork_rng.random() < DECFORK_RATE.get(screen, 0)):"
b = ("                    and not (screen == 'EVENT_SCREEN' and gc.event_id_string.upper() == 'NEOW')\n"
     "                    and decfork_rng.random() < DECFORK_RATE.get(screen, 0)):")
assert s.count(a) == 1
open("p300_play_v19.py", "w").write(s.replace(a, b))
PY
~/sts/venv/bin/python -c "import ast;ast.parse(open('p300_play_v19.py').read())" && echo patched
nohup bash ~/sts/runs/q37.sh > /dev/null 2>&1 < /dev/null &
sleep 2; ps -eo args | grep -c "[c]41-decfork"
