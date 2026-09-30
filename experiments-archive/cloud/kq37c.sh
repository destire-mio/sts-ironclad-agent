pkill -f "bash ~/sts/runs/q37.sh"
pkill -f "c41-dec""fork.jsonl"
sleep 5
cd ~/sts/principles/agent
cp p300_play_v19.py p300_play_v19.pre-shopplan.py
python3 ~/sts/runs/patch_shopplan.py && ~/sts/venv/bin/python -c "import ast;ast.parse(open('p300_play_v19.py').read())" && echo patched
