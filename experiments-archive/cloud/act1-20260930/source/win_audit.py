import json, glob, gzip, random, sys
from concurrent.futures import ProcessPoolExecutor
import p300_common as C

def job(path):
    run = json.load(gzip.open(path, "rt"))
    if run["status"] != "death" or not run.get("prefix"):
        return None
    game = dict(seed=run["seed"], prefix=run["prefix"])
    last = max(i for i, r in enumerate(run["prefix"]) if r["kind"] == "battle")
    for i, gc in C.battle_states(game):
        if i != last:
            continue
        g = C.F.copy_game(gc)
        r = C.F.resolve_reusing(g, 32000, 12.0)
        rec = run["prefix"][i]
        return dict(seed=run["seed"], act=int(gc.act), floor=int(gc.floor_num), encounter=gc.encounter.name,
                    boss=C.is_boss(gc), hp_in=int(gc.cur_hp), recorded_outcome=rec["outcome"],
                    same=[int(a) for a in r["actions"]] == rec["actions"], outcome=r["outcome"],
                    won=g.outcome != C.sts.GameOutcome.PLAYER_LOSS, best_hp=r["best_hp"], rounds=r["search_rounds"])

if __name__ == "__main__":
    paths = sorted(glob.glob("~/sts/runs/traj-c6/*.json.gz"))
    random.Random(5).shuffle(paths)
    with ProcessPoolExecutor(int(sys.argv[2])) as pool, open("~/sts/runs/win-audit.jsonl", "w") as f:
        for row in pool.map(job, paths[:int(sys.argv[1])]):
            if row:
                f.write(json.dumps(row) + "\n"); f.flush()
