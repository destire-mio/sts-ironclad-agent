pkill -f "bash ~/sts/runs/q37.sh"
pkill -f "c41-dec""fork.jsonl"
sleep 5
cd ~/sts/principles/agent
python3 - <<'PY'
s = open("p300_play_v19.py").read()
def rep(a, b):
    global s
    assert s.count(a) == 1, a
    s = s.replace(a, b)
rep("DECFORK_RATE = {'REST_ROOM': 0.8, 'SHOP_ROOM': 0.7, 'EVENT_SCREEN': 0.7, 'MAP_SCREEN': 0.12}",
    "DECFORK_RATE = {'REST_ROOM': 0.8, 'SHOP_ROOM': 0.7, 'EVENT_SCREEN': 0.7, 'MAP_SCREEN': 0.12, 'CARD_SELECT': 0.6}")
rep("DECFORK_CAP = {'REST_ROOM': 2, 'SHOP_ROOM': 1, 'EVENT_SCREEN': 1, 'MAP_SCREEN': 1}",
    "DECFORK_CAP = {'REST_ROOM': 2, 'SHOP_ROOM': 1, 'EVENT_SCREEN': 1, 'MAP_SCREEN': 1, 'CARD_SELECT': 2}")
rep("                    and not (screen == 'EVENT_SCREEN' and gc.event_id_string.upper() == 'NEOW')\n",
    "                    and not (screen == 'EVENT_SCREEN' and gc.event_id_string.upper() == 'NEOW')\n"
    "                    and not (screen == 'CARD_SELECT' and int(gc.selection_type) not in (3, 4))  # upgrade/remove only\n")
rep("event=gc.event_id_string if screen == 'EVENT_SCREEN' else None,",
    "event=gc.event_id_string if screen == 'EVENT_SCREEN' else None,\n"
    "                                         selection=int(gc.selection_type) if screen == 'CARD_SELECT' else None,")
open("p300_play_v19.py", "w").write(s)
PY
~/sts/venv/bin/python -c "import ast;ast.parse(open('p300_play_v19.py').read())" && echo patched
nohup bash ~/sts/runs/q37.sh > /dev/null 2>&1 < /dev/null &
sleep 2; ps -eo args | grep -c "[c]41-decfork"
