for p in $(pgrep -f "bash ~/sts/runs/q23.sh"); do kill $p; done
rm -f ~/sts/runs/c22-base2.jsonl
nohup bash ~/sts/runs/q24.sh >/dev/null 2>&1 &
echo swapped
