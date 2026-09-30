while pgrep -f apply_victory_hp_cloud >/dev/null; do sleep 30; done
[ -f ~/sts/combat4r/evidence/victory-hp/cloud-results.tar.gz ] || { echo "c4r update failed" > ~/sts/runs/c40.blocked; exit 1; }
while pgrep -f c39-cardfork2.jsonl >/dev/null && [ $(wc -l < ~/sts/runs/c39-cardfork2.jsonl) -lt 990 ]; do sleep 30; done
pkill -f c39-cardfork2.jsonl; sleep 10
cd ~/sts/principles/agent
export PYTHONPATH=~/sts/principles/agent P300_RUNTIME=~/sts/combat4r/runtime-delivery
B=sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide
mkdir -p ~/sts/runs/traj-c40
~/sts/venv/bin/python p300_play_v16.py ~/sts/runs/c40-c4r.jsonl --arms $B+c4r+heart2+fix2+baixi+eliteseek+fix3+spear320+traj --record-dir ~/sts/runs/traj-c40 --first-seed 3900012000 --games 2000 --workers 62 > ~/sts/runs/c40.log 2>&1
