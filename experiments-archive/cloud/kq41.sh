P="p300_play_v1""9.py"
pkill -f "$P"
sleep 5
pgrep -fc "$P"
wc -l < ~/sts/runs/c41-decfork.jsonl
