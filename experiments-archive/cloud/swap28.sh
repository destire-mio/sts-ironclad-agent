for p in $(pgrep -f "bash ~/sts/runs/q27.sh"); do kill $p; done
nohup bash ~/sts/runs/q28.sh >/dev/null 2>&1 &
echo ok
