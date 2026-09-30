for p in $(pgrep -f "bash ~/sts/runs/q24.sh") $(pgrep -f "bash ~/sts/runs/q25c.sh"); do kill $p; done
nohup bash ~/sts/runs/q27.sh >/dev/null 2>&1 &
echo ok
