kill 2833193
sleep 1
for p in $(pgrep -f "runs/c22-base2.jsonl"); do kill $p; done
sleep 3
nohup bash ~/sts/runs/q23.sh >/dev/null 2>&1 &
echo restarted
