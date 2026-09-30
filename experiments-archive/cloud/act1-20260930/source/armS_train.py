#!/usr/bin/env python3
"""Arm S — 底层:从零用 RL(REINFORCE)训一个小模型做"选卡"。
战斗/地图全交 sts_lightspeed 的 MCTS Agent;模型只在 CARD_REWARD 处打分选卡。
reward = 整局最终楼层(稀疏延迟),信用分配靠 REINFORCE。
跑: ~/lab/physical-world-ai/.venv/bin/python armS_train.py [train|eval] [n_games]
每局写 runs/armS-* 供 dashboard 看楼层曲线。
"""
import os, sys, json, time, random, statistics
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import slaythespire as sts
import obs
import torch, torch.nn as nn

# ---------- 卡牌词表(name->idx,持久化,稳定编码)----------
VOCAB_PATH = os.path.join(SB, "armS_card_vocab.json")
VOCAB_CAP = 256
_vocab = json.load(open(VOCAB_PATH)) if os.path.exists(VOCAB_PATH) else {}
import re
def card_name(c):
    m = re.search(r"Card (.+?)>", str(c));  return m.group(1) if m else str(c)
def card_idx(name):
    if name not in _vocab and len(_vocab) < VOCAB_CAP:
        _vocab[name] = len(_vocab)
    return _vocab.get(name, VOCAB_CAP - 1)   # 溢出归到最后一格
def save_vocab():
    json.dump(_vocab, open(VOCAB_PATH, "w"), ensure_ascii=False)

# ---------- 编码 ----------
_nn = sts.getNNInterface()
try:
    _maxes = [max(1.0, float(x)) for x in _nn.getObservationMaximums()]
except Exception:
    _maxes = None
def obs_vec(gc):
    o = list(_nn.getObservation(gc))
    if _maxes and len(_maxes) == len(o):
        o = [a / b for a, b in zip(o, _maxes)]        # 归一化
    return torch.tensor(o, dtype=torch.float32)
OBS_DIM = len(_nn.getObservation(sts.GameContext(sts.CharacterClass.IRONCLAD, 1, 0)))
INPUT_DIM = OBS_DIM + VOCAB_CAP                        # 局面 ⊕ 候选卡 one-hot

def cand_vec(name):
    v = torch.zeros(VOCAB_CAP); v[card_idx(name)] = 1.0; return v

# ---------- 打分网络(共享:f(局面⊕候选卡)->分) + skip 可学偏置 ----------
class Scorer(nn.Module):
    def __init__(self, arch=(128, 128)):
        super().__init__()
        layers, prev = [], INPUT_DIM
        for h in arch:
            layers += [nn.Linear(prev, h), nn.ReLU()]; prev = h
        layers += [nn.Linear(prev, 1)]
        self.net = nn.Sequential(*layers)
        self.skip_score = nn.Parameter(torch.zeros(1))   # skip 的可学分
    def score_cards(self, o, offered_names):
        rows = torch.stack([torch.cat([o, cand_vec(n)]) for n in offered_names])
        s = self.net(rows).squeeze(-1)                   # [k]
        return torch.cat([s, self.skip_score])           # [k+1], 末位=skip

# ---------- 跑一整局,模型在 CARD_REWARD 处决策 ----------
SIMCOUNT = int(os.environ.get("STS_SIM_COUNT", "2000"))   # MCTS 每步模拟次数(默认50000太慢)

def play_game(seed, net, train=True, max_steps=400):
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.pause_on_card_reward = True
    ag.simulation_count_base = SIMCOUNT
    logprobs = []; steps = 0
    while gc.outcome == sts.GameOutcome.UNDECIDED and steps < max_steps:
        steps += 1
        ag.playout(gc)
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break
        if gc.screen_state == sts.ScreenState.REWARDS:
            offered = gc.get_card_reward()
            if not offered:
                gc.skip_reward_cards(); continue
            names = [card_name(c) for c in offered]
            scores = net.score_cards(obs_vec(gc), names)        # [k+1]
            probs = torch.softmax(scores, dim=0)
            if train:
                a = torch.multinomial(probs, 1).item()
                logprobs.append(torch.log(probs[a] + 1e-9))
            else:
                a = int(torch.argmax(probs).item())
            if a == len(names):
                gc.skip_reward_cards()                          # 选了 skip
            else:
                gc.pick_reward_card(offered[a])
        else:
            break
    win = gc.outcome == sts.GameOutcome.PLAYER_VICTORY
    return {"floor": gc.floor_num, "act": gc.act, "win": win,
            "hp": gc.cur_hp, "deck": len(gc.deck)}, logprobs

def log_run(tag, seed, rep, oc):
    rid = f"armS-{tag}-s{seed}-r{rep:03d}"
    lg = obs.RunLogger(rid, meta={"seed": str(seed), "ascension": 0, "engine": "sts_lightspeed",
                                  "control": "card_reward", "memory_mode": "arm_s"})
    lg.finish({"result": "victory" if oc["win"] else "death", "floor": oc["floor"],
               "act": oc["act"], "hp": oc["hp"], "deck_size": oc["deck"]})

def read_seeds(fn):
    return [int(x) for x in open(os.path.join(SB, fn)) if x.strip() and not x.startswith("#")]

# ---------- 主：训练 / 评估 ----------
if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "train"
    print(f"INPUT_DIM={INPUT_DIM} (obs {OBS_DIM} ⊕ card {VOCAB_CAP})", flush=True)
    ARCH = tuple(int(x) for x in os.environ.get("ARM_S_ARCH", "128,128").split(","))
    net = Scorer(ARCH)
    CKPT = os.path.join(SB, "armS_model.pt")

    if mode == "train":
        reps = int(sys.argv[2]) if len(sys.argv) > 2 else 15
        seeds = read_seeds("train_seeds.txt")
        opt = torch.optim.Adam(net.parameters(), lr=1e-3)
        baseline = None; t0 = time.time(); floors = []
        games = [(s, r) for r in range(reps) for s in seeds]     # 交错 seed,别同seed连刷
        random.seed(0); random.shuffle(games)
        for i, (s, r) in enumerate(games):
            oc, logprobs = play_game(s, net, train=True)
            R = oc["floor"] / 50.0                                # 归一化 reward
            baseline = R if baseline is None else 0.95 * baseline + 0.05 * R
            if logprobs:
                loss = -(torch.stack(logprobs).sum()) * (R - baseline)
                opt.zero_grad(); loss.backward(); opt.step()
            floors.append(oc["floor"]); log_run("train", s, r, oc)
            if (i + 1) % 20 == 0:
                print(f"[{i+1}/{len(games)}] 近20局均楼层 {statistics.mean(floors[-20:]):.1f} "
                      f"baseline {baseline*50:.1f} 用时 {time.time()-t0:.0f}s", flush=True)
        torch.save(net.state_dict(), CKPT); save_vocab()
        print(f"\n训练完 {len(games)}局. 前50局均{statistics.mean(floors[:50]):.1f} → 后50局均{statistics.mean(floors[-50:]):.1f}", flush=True)

    elif mode == "eval":
        reps = int(sys.argv[2]) if len(sys.argv) > 2 else 15
        if os.path.exists(CKPT): net.load_state_dict(torch.load(CKPT, weights_only=True))
        seeds = read_seeds("test_seeds.txt"); floors = []
        for s in seeds:
            sf = []
            for r in range(reps):
                oc, _ = play_game(s, net, train=False)   # 评估 argmax
                sf.append(oc["floor"]); floors.append(oc["floor"]); log_run("eval", s, r, oc)
            print(f"seed {s}: {reps}局 平均 {statistics.mean(sf):.1f} 范围 {min(sf)}-{max(sf)}", flush=True)
        print(f"\nArm S eval 总均楼层 {statistics.mean(floors):.2f}", flush=True)
