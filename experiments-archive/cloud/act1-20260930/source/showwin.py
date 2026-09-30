import json, gzip, glob
import p300_common as C
sts = C.sts
rows = [json.loads(l) for l in open("~/sts/runs/c6-collect.jsonl")]
win = next(r for r in rows if r["win"] and r["seed"] >= 3900000010)
path = glob.glob("~/sts/runs/traj-c6/%d-*.json.gz" % win["seed"])[0]
run = json.load(gzip.open(path, "rt"))
gc = sts.GameContext(sts.CharacterClass.IRONCLAD, run["seed"], 20)
print("seed", run["seed"], run["status"])
name = lambda c: str(c.id).split(".")[-1] + ("+" if c.upgraded else "")
for row in run["prefix"]:
    C.H.clock_input(gc, C.CONFIG)
    if row["kind"] == "battle":
        b = sts.BattleContext(); b.init(gc)
        for bits in row["actions"]:
            sts.SearchAction.from_bits(bits & 0xffffffff).execute(b)
        b.exit_battle(gc)
        continue
    a = sts.GameAction(row["action"] & 0xffffffff)
    if gc.screen_state == sts.ScreenState.REWARDS:
        cards = gc.rewards.get("cards", []) if hasattr(gc.rewards, "get") else []
        rt = str(a.rewards_action_type).split(".")[-1]
        if cards and "CARD" in rt:
            offered = [[name(c) for c in g] for g in cards]
            print("F%-2d HP %d/%d offered %s -> %s idx1=%d idx2=%d" % (gc.floor_num, gc.cur_hp, gc.max_hp, offered, rt, a.idx1, a.idx2))
    a.execute(gc)
print("final deck:", sorted(name(c) for c in gc.deck))
print("relics:", [str(r.id).split(".")[-1] for r in gc.relics])
