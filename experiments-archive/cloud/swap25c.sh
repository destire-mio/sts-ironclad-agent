for p in $(pgrep -f "bash ~/sts/runs/q25b.sh") $(pgrep -f "bash ~/sts/runs/q26.sh"); do kill $p; done
nohup bash ~/sts/runs/q25c.sh >/dev/null 2>&1 &
echo ok
