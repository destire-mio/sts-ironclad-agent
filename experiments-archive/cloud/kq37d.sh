pkill -f "bash ~/sts/runs/q37.sh"
pkill -f "c41-dec""fork.jsonl"
sleep 5
cd ~/sts/principles/agent
python3 - <<'PY'
s = open("p300_play_v19.py").read()
a = "'MAP_SCREEN': 0.12, 'CARD_SELECT': 0.6}"
b = "'MAP_SCREEN': 0.12, 'CARD_SELECT': 0.6, 'BOSS_RELIC_REWARDS': 0.7}"
assert s.count(a) == 1; s = s.replace(a, b)
a = "'MAP_SCREEN': 1, 'CARD_SELECT': 2}"
b = "'MAP_SCREEN': 1, 'CARD_SELECT': 2, 'BOSS_RELIC_REWARDS': 1}"
assert s.count(a) == 1; s = s.replace(a, b)
open("p300_play_v19.py", "w").write(s)
PY
~/sts/venv/bin/python -c "import ast;ast.parse(open('p300_play_v19.py').read())" && echo patched
nohup bash ~/sts/runs/q37.sh > /dev/null 2>&1 < /dev/null &
sleep 2; ps -eo args | grep -c "[c]41-decfork"
