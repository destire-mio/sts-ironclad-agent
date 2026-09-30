pkill -f "bash ~/sts/runs/q33.sh"
nohup bash ~/sts/runs/q33b.sh > /dev/null 2>&1 &
sleep 1; ps -eo args | grep "[q]33"
