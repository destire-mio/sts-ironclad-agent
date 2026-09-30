#!/usr/bin/env python3
"""Arm S 并行训练:多进程 rollout(纯推理)+ 主进程批量 REINFORCE 更新。
不降 sim、不 shaping;靠并行提速 + 批量降方差。
跑: ~/lab/physical-world-ai/.venv/bin/python armS_train_parallel.py [n_games] [workers] [batch]
"""
import os, sys, json, time, random, statistics, tempfile
import multiprocessing as mp
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import torch
import armS_train as A   # 复用 Scorer / obs_vec / cand_vec / card_name / log_run / read_seeds

# 冻结词表(并行下各进程必须用同一份,禁止增长以防漂移)
def _frozen_idx(name):
    return A._vocab.get(name, A.VOCAB_CAP - 1)
A.card_idx = _frozen_idx     # monkeypatch:只查不加

SIMCOUNT = int(os.environ.get("STS_SIM_COUNT", "2000"))
ARCH = tuple(int(x) for x in os.environ.get("ARM_S_ARCH", "128,128").split(","))   # 网络形状,可配

# ---------- worker:用给定权重打一局,回传轨迹(可pickle的纯数据)----------
def worker_play(args):
    seed, wpath, *rest = args
    greedy = rest[0] if rest else False          # eval 用贪心(argmax),训练用采样
    import slaythespire as sts
    net = A.Scorer(ARCH)
    net.load_state_dict(torch.load(wpath, weights_only=True)); net.eval()
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.pause_on_card_reward = True; ag.simulation_count_base = SIMCOUNT
    traj = []; steps = 0
    while gc.outcome == sts.GameOutcome.UNDECIDED and steps < 400:
        steps += 1; ag.playout(gc)
        if gc.outcome != sts.GameOutcome.UNDECIDED: break
        if gc.screen_state == sts.ScreenState.REWARDS:
            offered = gc.get_card_reward()
            if not offered: gc.skip_reward_cards(); continue
            names = [A.card_name(c) for c in offered]
            o = A.obs_vec(gc)
            with torch.no_grad():
                scores = net.score_cards(o, names)
                a = int(torch.argmax(scores).item()) if greedy else torch.multinomial(torch.softmax(scores, dim=0), 1).item()
            traj.append((o.tolist(), names, a))      # 存:局面向量、候选名、选了第几个
            if a == len(names): gc.skip_reward_cards()
            else: gc.pick_reward_card(offered[a])
        else: break
    win = gc.outcome == sts.GameOutcome.PLAYER_VICTORY
    return {"seed": seed, "floor": gc.floor_num, "act": gc.act, "win": win,
            "hp": gc.cur_hp, "deck": len(gc.deck), "traj": traj}

# ---------- 主进程:重算 logprob(带梯度)+ 批量更新 ----------
def game_loss(net, traj, adv):
    lps = []
    for o_list, names, a in traj:
        o = torch.tensor(o_list, dtype=torch.float32)
        scores = net.score_cards(o, names)              # [k+1],带梯度
        lps.append(torch.log_softmax(scores, dim=0)[a])
    if not lps: return None
    return -(torch.stack(lps).sum()) * adv

if __name__ == "__main__":
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    W = int(sys.argv[2]) if len(sys.argv) > 2 else max(2, mp.cpu_count() - 2)
    BATCH = int(sys.argv[3]) if len(sys.argv) > 3 else 32
    EVAL_EVERY = int(os.environ.get("EVAL_EVERY", "250"))      # 每多少局在留出集 eval 一次
    TAG = os.environ.get("PROG_TAG", "x".join(str(a) for a in ARCH))
    print(f"并行训练: {N}局 {W}workers batch{BATCH} sim{SIMCOUNT} arch{ARCH} | 每{EVAL_EVERY}局eval一次", flush=True)
    net = A.Scorer(ARCH); opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    eval_seeds = A.read_seeds("eval_seeds_50.txt")            # 固定50个留出seed,所有模型同一批
    eset = set(eval_seeds); rng = random.Random(0)
    games = []                                               # 训练:每局随机抽新seed(几乎无限多样,防过拟合)
    while len(games) < N:
        s = rng.randint(1, 10**9)
        if s not in eset: games.append(s)
    baseline = None; floors = []; t0 = time.time()
    TRACK = os.path.join(SB, f"armS_track_{TAG}.jsonl"); tf = open(TRACK, "w")
    from torch.utils.tensorboard import SummaryWriter
    import shutil
    tbdir = os.path.join(SB, "tb_armS", TAG); shutil.rmtree(tbdir, ignore_errors=True)
    tbw = SummaryWriter(log_dir=tbdir)                        # TensorBoard:带轴/可hover的曲线
    wpath = os.path.join(tempfile.gettempdir(), "armS_w.pt")
    ckdir = os.path.join(SB, "ckpts_" + TAG); shutil.rmtree(ckdir, ignore_errors=True); os.makedirs(ckdir)
    best_ev = -1.0; best_ck = None                           # 早停用:追踪 eval 最高的那一份存档
    ctx = mp.get_context("spawn")
    with ctx.Pool(W) as pool:
        def eval_set():                                       # 在固定50个留出seed上并行贪心评估
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
            if done >= next_eval:                              # 到点:记 train(随机训练seed近况)+ eval(固定50留出)
                tr = statistics.mean(floors[-EVAL_EVERY:]); ev = eval_set()
                tf.write(json.dumps({"game": done, "train": round(tr, 2), "eval": round(ev, 2)}) + "\n"); tf.flush()
                tbw.add_scalar("floor/train", tr, done); tbw.add_scalar("floor/eval", ev, done); tbw.flush()
                ckpath = os.path.join(ckdir, f"step{done}_eval{ev:.1f}.pt")   # 每次eval存一份冻结快照,供回溯/早停
                torch.save(net.state_dict(), ckpath)
                star = ""
                if ev > best_ev: best_ev = ev; best_ck = ckpath; star = " ★new-best"   # 实时追踪最优档
                print(f"[{done}/{N}] train {tr:.1f} | eval {ev:.1f} | gap {tr-ev:+.1f} | {time.time()-t0:.0f}s{star}", flush=True)
                next_eval += EVAL_EVERY
        final_eval = eval_set()
    torch.save(net.state_dict(), os.path.join(SB, f"armS_model_{TAG}.pt"))   # 末档(可能已过度收敛)
    print(f"\n训练完 {done}局 arch{ARCH}. 末train {statistics.mean(floors[-EVAL_EVERY:]):.1f} | 末eval {final_eval:.1f} | {(time.time()-t0)/60:.0f}分", flush=True)
    print(f"早停最优档: {os.path.basename(best_ck) if best_ck else '(无)'} | best_eval {best_ev:.1f} | 全部存档在 {ckdir}/", flush=True)
