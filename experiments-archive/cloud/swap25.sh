for p in $(pgrep -f "bash ~/sts/runs/q25.sh"); do kill $p; done
nohup bash ~/sts/runs/q25b.sh >/dev/null 2>&1 &
echo ok
