#!/usr/bin/env python3
"""Arm G 并行训练:多进程 rollout(纯推理回传轨迹)+ 主进程批量 REINFORCE。
模型做【全部非战斗决策】,战斗交 MCTS。控制变量:sim、固定50 eval seed、checkpoint 机制全沿用 Arm S。
跑: ~/lab/physical-world-ai/.venv/bin/python armG_train_parallel.py [n_games] [workers] [batch]
"""
import os, sys, json, time, random, statistics, tempfile, shutil
import multiprocessing as mp
import torch
import armG_train as A      # 复用 Scorer / build_choices / play_game / obs / read_seeds

SB = A.SB

ARCH = tuple(int(x) for x in os.environ.get("ARM_G_ARCH", "128,128").split(","))

# ---------- worker:用给定权重打一局,回传轨迹(纯数据)----------
def worker_play(args):
    seed, wpath, *rest = args
    greedy = rest[0] if rest else False
    net = A.Scorer(ARCH)
    net.load_state_dict(torch.load(wpath, weights_only=True)); net.eval()
    r = A.play_game(seed, net, train=not greedy)
    if greedy:
        r["traj"] = []          # eval 不需要轨迹,省 pickle
    return r

# ---------- 主进程:重算 logprob(带梯度)+ 批量更新 ----------
def game_loss(net, traj, adv):
    lps = []
    for o, descs, a in traj:
        scores = net.score(torch.tensor(o, dtype=torch.float32), descs)   # [k],带梯度
        lps.append(torch.log_softmax(scores, dim=0)[a])
    if not lps:
        return None
    return -(torch.stack(lps).sum()) * adv

if __name__ == "__main__":
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    W = int(sys.argv[2]) if len(sys.argv) > 2 else max(2, mp.cpu_count() - 2)
    BATCH = int(sys.argv[3]) if len(sys.argv) > 3 else 32
    EVAL_EVERY = int(os.environ.get("EVAL_EVERY", "400"))
    TAG = os.environ.get("PROG_TAG", "G_" + "x".join(str(a) for a in ARCH))
    print(f"Arm G 并行: {N}局 {W}workers batch{BATCH} sim{A.SIMCOUNT} arch{ARCH} input{A.INPUT_DIM} | 每{EVAL_EVERY}局eval", flush=True)

    net = A.Scorer(ARCH); opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    eval_seeds = A.read_seeds("eval_seeds_50.txt"); eset = set(eval_seeds)
    rng = random.Random(0)
    games = []
    while len(games) < N:
        s = rng.randint(1, 10**9)
        if s not in eset: games.append(s)

    baseline = None; floors = []; t0 = time.time()
    TRACK = os.path.join(SB, f"armG_track_{TAG}.jsonl"); tf = open(TRACK, "w")
    from torch.utils.tensorboard import SummaryWriter
    tbdir = os.path.join(SB, "tb_armS", TAG); shutil.rmtree(tbdir, ignore_errors=True)
    tbw = SummaryWriter(log_dir=tbdir)
    ckdir = os.path.join(SB, "ckpts_" + TAG); shutil.rmtree(ckdir, ignore_errors=True); os.makedirs(ckdir)
    best_ev = -1.0; best_ck = None
    wpath = os.path.join(tempfile.gettempdir(), "armG_w.pt")
    ctx = mp.get_context("spawn")
    with ctx.Pool(W) as pool:
        def eval_set():
            torch.save(net.state_dict(), wpath)
            ef = pool.map(worker_play, [(s, wpath, True) for s in eval_seeds])
            return statistics.mean(r["floor"] for r in ef)
        done = 0; next_eval = EVAL_EVERY
        for b in range(0, len(games), BATCH):
            batch = games[b:b + BATCH]
            torch.save(net.state_dict(), wpath)
            results = pool.map(worker_play, [(s, wpath) for s in batch])
            opt.zero_grad(); losses = []
            for r in results:
                R = r["floor"] / 50.0
                baseline = R if baseline is None else 0.99 * baseline + 0.01 * R
                l = game_loss(net, r["traj"], R - baseline)
                if l is not None: losses.append(l)
                floors.append(r["floor"]); done += 1
            if losses:
                (torch.stack(losses).mean()).backward(); opt.step()
            if done >= next_eval:
                tr = statistics.mean(floors[-EVAL_EVERY:]); ev = eval_set()
                tf.write(json.dumps({"game": done, "train": round(tr, 2), "eval": round(ev, 2)}) + "\n"); tf.flush()
                tbw.add_scalar("floor/train", tr, done); tbw.add_scalar("floor/eval", ev, done); tbw.flush()
                ckpath = os.path.join(ckdir, f"step{done}_eval{ev:.1f}.pt"); torch.save(net.state_dict(), ckpath)
                star = ""
                if ev > best_ev: best_ev = ev; best_ck = ckpath; star = " ★new-best"
                print(f"[{done}/{N}] train {tr:.1f} | eval {ev:.1f} | gap {tr-ev:+.1f} | {time.time()-t0:.0f}s{star}", flush=True)
                next_eval += EVAL_EVERY
        final_eval = eval_set()
    torch.save(net.state_dict(), os.path.join(SB, f"armG_model_{TAG}.pt"))
    print(f"\n训练完 {done}局 arch{ARCH}. 末train {statistics.mean(floors[-EVAL_EVERY:]):.1f} | 末eval {final_eval:.1f} | {(time.time()-t0)/60:.0f}分", flush=True)
    print(f"早停最优档: {os.path.basename(best_ck) if best_ck else '(无)'} | best_eval {best_ev:.1f} | 存档在 {ckdir}/", flush=True)
