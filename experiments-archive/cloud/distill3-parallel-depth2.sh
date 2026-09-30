#!/usr/bin/env bash
# Run bc-depth2 concurrently with the pipeline's bc-depth1; write bc-depth2.done.json so the pipeline skips it.
OUT=~/sts/runs/distill3-v21-20260930
cd ~/sts/runs/distill3-code-v1
export P300_RUNTIME=$OUT/source/combat4r/runtime-delivery PYTHONPATH=$OUT/source/principles/agent PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
until [ -f $OUT/bc-depth1.started.json ]; do sleep 10; done
CMD=(~/sts/venv/bin/python ~/sts/runs/distill3-code-v1/distill3_train.py --data $OUT/data --init $OUT/warm-start-distill2.pt --output $OUT/bc-depth2 --depth 2 --epochs 8 --patience 2 --threads 7 --target-weight 5 --lr 0.0001)
python3 - "$OUT" "${CMD[@]}" <<PY
import json,sys,time
out=sys.argv[1]; json.dump(dict(stage="bc-depth2",started=time.time(),command=sys.argv[2:],note="run in parallel by operator"),open(out+"/bc-depth2.started.json","w"),indent=2)
PY
nice -n 10 "${CMD[@]}" > $OUT/bc-depth2.log 2>&1
RC=$?
python3 - "$OUT" "$RC" <<PY
import json,sys,time
out,rc=sys.argv[1],int(sys.argv[2]); s=json.load(open(out+"/bc-depth2.started.json")); s.update(ended=time.time(),exit_code=rc)
if rc==0: json.dump(s,open(out+"/bc-depth2.done.json","w"),indent=2)
PY
