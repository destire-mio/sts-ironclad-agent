for p in $(pgrep -f "bash ~/sts/runs/q31.sh"); do kill $p; done
nohup bash ~/sts/runs/q31b.sh >/dev/null 2>&1 &
echo ok
