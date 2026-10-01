// 05 读取真实随机数推演未来抽牌: the random-number state is read out of the real
// game and copied into the simulator, which can then predict the next draws.
import { C, p, ease, clamp, lerp, rgba, text, glow, panel, chapter, TAU, chip, scramble, rr, bez } from '../engine.js';
import * as I from '../icons.js';
import { card, CARDS } from '../widgets.js';

const LW = { x: 110, y: 262, w: 780, h: 612 };
const RW = { x: 1030, y: 262, w: 780, h: 612 };
const STREAMS = [
  { label: '洗牌', name: 'shuffleRng', value: '7213459983311729', n: 37 },
  { label: '卡牌', name: 'cardRandomRng', value: '0482913376650218', n: 112 },
  { label: '怪物', name: 'aiRng', value: '5590127734481906', n: 9 },
];
const DRAW = [CARDS.shrug, CARDS.bash, CARDS.strike, CARDS.inflame, CARDS.defend];
const NEXT = [CARDS.strike, CARDS.defend, CARDS.pommel, CARDS.heavy, CARDS.defend];
const HAND_Y = 466, NEXT_Y = 570;
const T_READ = 2.9, T_COPY = 4.8, T_SIM = 6.6, T_REAL = 10.4, T_END = 13.6;

function windowFrame(ctx, w, title, sub, col, a) {
  panel(ctx, w.x, w.y, w.w, w.h, { alpha: a, glow: col, glowA: 0.08 });
  ctx.save();
  ctx.globalAlpha *= a;
  rr(ctx, w.x, w.y, w.w, 50, [20, 20, 0, 0]);
  ctx.fillStyle = 'rgba(255,255,255,0.04)';
  ctx.fill();
  ['#ff5f57', '#febc2e', '#28c840'].forEach((c, i) => {
    ctx.beginPath();
    ctx.arc(w.x + 26 + i * 20, w.y + 25, 6, 0, TAU);
    ctx.fillStyle = rgba(c, 0.8);
    ctx.fill();
  });
  text(ctx, title, w.x + 100, w.y + 33, { size: 22, weight: 700, color: col });
  text(ctx, sub, w.x + w.w - 24, w.y + 33, { size: 17, color: C.sub, align: 'right' });
  ctx.restore();
}

function rngRows(ctx, w, t, k, o) {
  // k: lock progress 0..1 (left to right), o.alpha
  const x0 = w.x + 30, y0 = w.y + 98;
  STREAMS.forEach((s, i) => {
    const y = y0 + i * 52;
    const ki = clamp(k * 1.3 - i * 0.15);
    ctx.save();
    ctx.globalAlpha *= o.alpha ?? 1;
    I.dice(ctx, x0 + 12, y - 8, 24, C.violet, { face: [5, 3, 6][i], rot: 0.2 + i * 0.3 });
    text(ctx, s.label, x0 + 38, y, { size: 21, weight: 700 });
    text(ctx, s.name, x0 + 92, y, { size: 16, fam: 'mono', color: C.dim });
    const shown = ki > 0 ? scramble(s.value, ki, i + (o.seed ?? 0), t) : '················';
    const grouped = shown.replace(/(.{4})/g, '$1 ').trim();
    rr(ctx, x0 + 250, y - 27, 330, 38, 8);
    ctx.fillStyle = rgba(C.violet, 0.08 + 0.1 * (ki >= 1 ? 1 : 0));
    ctx.fill();
    text(ctx, grouped, x0 + 266, y, { size: 21, weight: 600, fam: 'mono', color: ki >= 1 ? C.violet : C.sub });
    text(ctx, ki >= 1 ? `已用 ${s.n} 次` : '', x0 + 600, y, { size: 18, color: C.sub });
    ctx.restore();
  });
}

function pile(ctx, x, y, n, a, lift = 0) {
  for (let i = n - 1; i >= 0; i--) card(ctx, x + i * 1.5, y - i * 2.5 - (i === 0 ? lift : 0), CARDS.strike, { scale: 0.5, flip: 1, alpha: a });
}

// Five cards flying from a pile to hand slots and flipping face up.
function deal(ctx, w, t, t0, cards, o = {}) {
  const px = w.x + 92, py = w.y + HAND_Y;
  const out = [];
  cards.forEach((cd, j) => {
    const s = t0 + j * 0.32;
    const fly = p(t, s, 0.45, ease.inOutCubic);
    if (fly <= 0) return;
    const tx = w.x + 232 + j * 108, ty = w.y + HAND_Y;
    const x = lerp(px, tx, fly), y = lerp(py, ty, fly) - Math.sin(fly * Math.PI) * 50;
    const flip = 1 - p(t, s + 0.4, 0.35, ease.inOutQuad);
    card(ctx, x, y, cd, { scale: 0.58, flip, rot: (1 - fly) * -0.3, glow: o.glow ? o.glow(j) : 0, glowColor: o.glowColor });
    out.push({ x: tx, y: ty, shown: flip < 0.5 });
  });
  return out;
}

export default {
  id: 's05',
  num: '05',
  file: '05-rng',
  title: '读取真实随机数，推演未来抽牌',
  duration: 18,
  draw(ctx, t) {
    chapter(ctx, t, { num: '05', title: '读取真实随机数，推演未来抽牌', sub: '游戏里的"随机"是一串确定的计算：拿到状态，就能算出接下来抽到什么' });

    const wa = p(t, 2.0, 0.7);
    windowFrame(ctx, LW, '真实游戏', '原版 · 当前回合', C.ink, wa);
    windowFrame(ctx, RW, '模拟器', '复制同一份状态', C.red, p(t, 2.2, 0.7));

    // ---- RNG readout: left reads, right receives
    const readK = p(t, T_READ, 1.5, ease.inOutQuad);
    rngRows(ctx, LW, t, readK, { alpha: wa, seed: 0 });
    // scan line
    if (t > T_READ && t < T_READ + 1.7) {
      const sx = lerp(LW.x + 270, LW.x + 640, clamp((t - T_READ) / 1.5));
      glow(ctx, sx, LW.y + 150, 90, C.violet, 0.5, 0.15, 1.1);
    }
    const copyK = p(t, T_COPY + 0.6, 1.1, ease.inOutQuad);
    rngRows(ctx, RW, t, copyK, { alpha: p(t, 2.2, 0.7), seed: 5 });
    // the numbers travel across as small packets, one per 4-digit group
    STREAMS.forEach((s, i) => {
      const y = LW.y + 90 + i * 52;
      const P = [{ x: LW.x + 600, y: y - 8 }, { x: 900, y: y - 52 }, { x: 1020, y: y - 52 }, { x: RW.x + 300, y: y - 8 }];
      const lk = p(t, T_COPY + i * 0.1, 0.4) * (1 - p(t, T_COPY + 1.9, 0.4));
      if (lk > 0) {
        ctx.save();
        ctx.globalAlpha *= lk;
        ctx.setLineDash([3, 7]);
        ctx.strokeStyle = rgba(C.violet, 0.45);
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        for (let q = 0; q <= 30; q++) {
          const pt = bez(P, q / 30);
          q ? ctx.lineTo(pt.x, pt.y) : ctx.moveTo(pt.x, pt.y);
        }
        ctx.stroke();
        ctx.restore();
      }
      for (let d = 0; d < 4; d++) {
        const k = clamp((t - T_COPY - 0.15 - i * 0.14 - d * 0.16) / 0.85);
        if (k <= 0 || k >= 1) continue;
        const q = bez(P, ease.inOutCubic(k));
        const a = Math.min(1, Math.sin(k * Math.PI) * 2.5);
        glow(ctx, q.x, q.y, 34, C.violet, 0.5 * a);
        ctx.save();
        ctx.globalAlpha *= a;
        rr(ctx, q.x - 30, q.y - 15, 60, 30, 8);
        ctx.fillStyle = rgba('#3a2c6e', 0.95);
        ctx.fill();
        ctx.strokeStyle = rgba(C.violet, 0.9);
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.restore();
        text(ctx, s.value.slice(d * 4, d * 4 + 4), q.x, q.y + 6, { size: 16, weight: 700, fam: 'mono', color: '#f1ebff', align: 'center', alpha: a });
      }
    });
    const eqK = p(t, T_COPY + 1.6, 0.5, ease.outBack);
    if (eqK > 0) {
      ctx.save();
      ctx.translate(960, LW.y + 150);
      ctx.scale(eqK, eqK);
      glow(ctx, 0, 0, 60, C.green, 0.4);
      text(ctx, '=', 0, 18, { size: 60, weight: 900, align: 'center', color: C.green });
      ctx.restore();
      text(ctx, '完全相同', 960, LW.y + 200, { size: 18, weight: 700, align: 'center', color: C.green, alpha: clamp(eqK) });
    }
    chip(ctx, LW.x + 30, LW.y + 268, '读出完整的随机数状态', { color: C.violet, size: 18, alpha: p(t, T_READ + 0.3, 0.5), icon: I.dice });

    // divider between rng and cards
    [LW, RW].forEach((w, i) => {
      ctx.save();
      ctx.globalAlpha *= p(t, 2.3 + i * 0.2, 0.6);
      ctx.strokeStyle = 'rgba(255,255,255,0.07)';
      ctx.beginPath();
      ctx.moveTo(w.x + 24, w.y + 300);
      ctx.lineTo(w.x + w.w - 24, w.y + 300);
      ctx.stroke();
      ctx.restore();
    });

    // ---- piles
    const pileA = p(t, 2.5, 0.6);
    const leftDealt = t >= T_REAL ? Math.min(5, Math.floor((t - T_REAL) / 0.32) + 1) : 0;
    const rightDealt = t >= T_SIM ? Math.min(5, Math.floor((t - T_SIM) / 0.32) + 1) : 0;
    pile(ctx, LW.x + 92, LW.y + HAND_Y, Math.max(2, 9 - leftDealt), pileA);
    pile(ctx, RW.x + 92, RW.y + HAND_Y, Math.max(2, 9 - rightDealt), pileA);
    text(ctx, '抽牌堆', LW.x + 92, LW.y + HAND_Y + 92, { size: 17, color: C.sub, align: 'center', alpha: pileA });
    text(ctx, '抽牌堆', RW.x + 92, RW.y + HAND_Y + 92, { size: 17, color: C.sub, align: 'center', alpha: pileA });

    // ---- simulator predicts
    const simLabel = p(t, T_SIM - 0.3, 0.5);
    text(ctx, '推演：下一回合会抽到', RW.x + 232 - 41, RW.y + 352, { size: 20, weight: 700, color: C.red, alpha: simLabel });
    const sim = deal(ctx, RW, t, T_SIM, DRAW, {
      glow: (j) => (t > T_REAL + j * 0.32 + 0.75 ? Math.exp(-(t - (T_REAL + j * 0.32 + 0.75)) * 2.5) : 0),
      glowColor: C.green,
    });
    // future turn row (small)
    const nk = p(t, T_SIM + 2.0, 0.5);
    text(ctx, '再下一回合', RW.x + 191, RW.y + NEXT_Y + 6, { size: 17, color: C.sub, alpha: nk });
    NEXT.forEach((cd, j) => {
      const k = p(t, T_SIM + 2.1 + j * 0.1, 0.4, ease.outBack);
      card(ctx, RW.x + 330 + j * 62, RW.y + NEXT_Y, cd, { scale: 0.3, alpha: clamp(k) * 0.85 });
    });

    // ---- the real game draws
    const realLabel = p(t, T_REAL - 0.3, 0.5);
    text(ctx, '实际抽到', LW.x + 191, LW.y + 352, { size: 20, weight: 700, color: C.ink, alpha: realLabel });
    const real = deal(ctx, LW, t, T_REAL, DRAW);
    // matches: checks above both copies of each card
    real.forEach((c, j) => {
      if (!c.shown || !sim[j]) return;
      const k = ease.outBack(p(t, T_REAL + j * 0.32 + 0.75, 0.4));
      I.check(ctx, c.x, LW.y + HAND_Y - 84, 28 * k, C.green);
      I.check(ctx, sim[j].x, RW.y + HAND_Y - 84, 28 * k, C.green);
    });
    const mk = p(t, T_REAL + 2.4, 0.5, ease.outBack);
    if (mk > 0) {
      ctx.save();
      ctx.translate(960, LW.y + HAND_Y - 20);
      ctx.scale(mk, mk);
      glow(ctx, 0, 0, 70, C.green, 0.35);
      I.check(ctx, 0, 0, 46, C.green);
      text(ctx, '全部', 0, 52, { size: 20, weight: 700, align: 'center', color: C.green });
      text(ctx, '对上', 0, 78, { size: 20, weight: 700, align: 'center', color: C.green });
      ctx.restore();
    }

    // ---- conclusion
    const ck = p(t, T_END, 0.7);
    text(ctx, '同一份随机数 → 同一个未来：搜索能把接下来几回合算准', 960, 932, { size: 30, weight: 700, align: 'center', alpha: ck });
    chip(ctx, 1810, 200, '只有战斗搜索用它；局外网络看不到种子和随机数', { color: C.cyan, size: 19, align: 'right', alpha: p(t, T_END + 0.5, 0.6), icon: I.eye });
  },
};
