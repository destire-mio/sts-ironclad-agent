for p in $(pgrep -f "p300_play_v19.py"); do renice -n 10 -p $p >/dev/null; done
nohup bash ~/sts/runs/q38.sh > /dev/null 2>&1 < /dev/null &
sleep 3; ps -eo ni,args | grep "[p]300_play" | awk '{print $1, $3}' | sort | uniq -c
