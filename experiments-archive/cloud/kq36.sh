pkill -f "bash ~/sts/runs/q36.sh"
nohup bash ~/sts/runs/q36b.sh > ~/sts/runs/q36.out 2>&1 < /dev/null &
sleep 1; ps -eo args | grep "[q]36"
