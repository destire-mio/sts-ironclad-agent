pkill -f "bash ~/sts/runs/q36b.sh"
pkill -f c40-c4r.jsonl
sleep 2; ps -eo args | grep -c "[c]40-c4r"; ps -eo args | grep "[q]36"
