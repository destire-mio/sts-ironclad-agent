pkill -f "bash ~/sts/runs/q34.sh"
nohup bash ~/sts/runs/q34b.sh > /dev/null 2>&1 &
sleep 1; ps -eo args | grep "[q]34"
