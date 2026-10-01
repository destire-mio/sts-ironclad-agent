// 01 片头: a tower whose inside is the run's map. A light climbs node by node,
// collects the three keys and reaches the Heart; the title lands beside it.
import { C, H, TAU, p, ease, clamp, lerp, rgba, text, textReveal, glow, ring, chip, measure } from '../engine.js';
import * as I from '../icons.js';

const TX = 1390; // tower centre x
const TIERS = [
  [1110, 280], [900, 228], [740, 182], [600, 140], [480, 104], [380, 74], [292, 50],
];
const NODES = [
  ['start', 0, 1012], ['fight', -92, 934], ['event', 74, 856], ['elite', -64, 778],
  ['fight', 62, 700], ['rest', -44, 622], ['shop', 46, 548], ['chest', -26, 474],
  ['fight', 22, 402], ['boss', 0, 336],
];
const HEART = { x: TX, y: 196 };
// Keys: emerald from a burning elite, ruby from a campfire, sapphire from a chest.
const KEYS = [
  { node: 3, color: '#4fe08a', angle: Math.PI * 0.95 },
  { node: 5, color: '#ff4d5e', angle: Math.PI * 1.5 },
  { node: 7, color: '#5aa8ff', angle: Math.PI * 0.05 },
];

function outline() {
  // Left edge bottom→top then right edge top→bottom, with small ledges per tier.
  const left = [], right = [];
  for (let i = 0; i < TIERS.length; i++) {
    const [y, hw] = TIERS[i];
    const next = TIERS[i + 1];
    left.push([TX - hw, y]);
    if (next) {
      left.push([TX - hw + 6, next[0] + 16]);
      left.push([TX - next[1] - 12, next[0] + 16]);
    }
  }
  const top = TIERS[TIERS.length - 1];
  left.push([TX - top[1] - 14, top[0] - 34]); // horn
  left.push([TX - top[1] + 8, top[0]]);
  for (let i = TIERS.length - 1; i >= 0; i--) {
    const [y, hw] = TIERS[i];
    const next = TIERS[i + 1];
    if (!next) {
      right.push([TX + hw - 8, y]);
      right.push([TX + hw + 14, y - 34]);
      right.push([TX + hw, y]);
      continue;
    }
    right.push([TX + next[1] + 12, next[0] + 16]);
    right.push([TX + hw - 6, next[0] + 16]);
    right.push([TX + hw, y]);
  }
  return [...left, ...right];
}
const OUTLINE = outline();
const OUT_LEN = OUTLINE.reduce((s, q, i) => (i ? s + Math.hypot(q[0] - OUTLINE[i - 1][0], q[1] - OUTLINE[i - 1][1]) : 0), 0);

function nodePos(i) {
  if (i >= NODES.length) return { x: HEART.x, y: HEART.y };
  return { x: TX + NODES[i][1], y: NODES[i][2] };
}

function climbPos(c) {
  const i = Math.floor(clamp(c, 0, NODES.length - 0.0001));
  const f = ease.inOutSine(clamp(c - i));
  const a = nodePos(i), b = nodePos(i + 1);
  return { x: lerp(a.x, b.x, f), y: lerp(a.y, b.y, f) };
}

function drawTower(ctx, t, climbY = H) {
  const k = p(t, 0.15, 2.2, ease.inOutCubic);
  // fill
  ctx.save();
  ctx.beginPath();
  OUTLINE.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.closePath();
  const g = ctx.createLinearGradient(0, 250, 0, H);
  g.addColorStop(0, 'rgba(32,26,58,0.92)');
  g.addColorStop(1, 'rgba(14,12,26,0.96)');
  ctx.globalAlpha *= p(t, 0.6, 1.6);
  ctx.fillStyle = g;
  ctx.fill();
  // inner bricks: faint horizontal courses
  ctx.clip();
  ctx.strokeStyle = 'rgba(255,255,255,0.035)';
  ctx.lineWidth = 1;
  for (let y = 300; y < H; y += 26) {
    ctx.beginPath();
    ctx.moveTo(TX - 300, y);
    ctx.lineTo(TX + 300, y);
    ctx.stroke();
  }
  ctx.restore();
  // tier ledges and window slits that light up as the climber rises
  for (let i = 1; i < TIERS.length; i++) {
    const [y, hw] = TIERS[i];
    const a = p(t, 0.8 + (TIERS.length - i) * 0.12, 0.6);
    ctx.save();
    ctx.globalAlpha *= a * 0.5;
    ctx.strokeStyle = rgba(C.gold, 0.35);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(TX - hw + 10, y + 16);
    ctx.lineTo(TX + hw - 10, y + 16);
    ctx.stroke();
    ctx.restore();
    const prev = TIERS[i - 1];
    const wy = (y + prev[0]) / 2 + 10;
    const lit = climbY < wy + 30 ? 1 : 0;
    [-1, 1].forEach((sd) => {
      const wx = TX + sd * (prev[1] * 0.78 - 6);
      ctx.save();
      ctx.globalAlpha *= a;
      ctx.beginPath();
      ctx.roundRect(wx - 5, wy - 16, 10, 28, [5, 5, 1, 1]);
      ctx.fillStyle = lit ? '#ffc56b' : 'rgba(255,255,255,0.06)';
      ctx.fill();
      ctx.restore();
      if (lit) glow(ctx, wx, wy, 26, C.orange, 0.6);
    });
  }
  // outline draw-on
  ctx.save();
  ctx.beginPath();
  OUTLINE.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.strokeStyle = rgba(C.gold, 0.75);
  ctx.lineWidth = 2.2;
  ctx.lineJoin = 'round';
  ctx.setLineDash([OUT_LEN * k, OUT_LEN]);
  ctx.shadowColor = rgba(C.gold, 0.6);
  ctx.shadowBlur = 12;
  ctx.stroke();
  ctx.restore();
}

function drawPath(ctx, t, c) {
  const k = p(t, 0.9, 1.3, ease.inOutQuad);
  ctx.save();
  ctx.setLineDash([2, 9]);
  ctx.lineCap = 'round';
  ctx.lineWidth = 2.5;
  ctx.strokeStyle = 'rgba(255,240,220,0.35)';
  ctx.beginPath();
  const n = NODES.length;
  for (let i = 0; i < n; i++) {
    const q = nodePos(i);
    if (i === 0) ctx.moveTo(q.x, q.y);
    else {
      const prev = nodePos(i - 1);
      const kk = clamp(k * n - (i - 1));
      if (kk <= 0) break;
      ctx.lineTo(lerp(prev.x, q.x, kk), lerp(prev.y, q.y, kk));
    }
  }
  ctx.stroke();
  ctx.restore();
  // nodes
  NODES.forEach(([kind], i) => {
    const q = nodePos(i);
    const appear = p(t, 0.9 + i * 0.09, 0.5, ease.outBack);
    const lit = c >= i ? Math.max(0.35, 1 - (c - i) * 0.5) : 0;
    const r = kind === 'boss' ? 25 : 21;
    ctx.save();
    ctx.translate(q.x, q.y);
    ctx.scale(appear, appear);
    I.mapNode(ctx, 0, 0, r, kind, { active: lit, alpha: clamp(appear) });
    ctx.restore();
  });
}

function heartBeat(t) {
  const ph = (t % 1.1) / 1.1;
  return Math.exp(-Math.pow((ph - 0.08) * 22, 2)) * 0.07 + Math.exp(-Math.pow((ph - 0.28) * 22, 2)) * 0.045;
}

function drawHeart(ctx, t, arrive) {
  const show = p(t, 1.4, 0.9);
  if (show <= 0) return;
  const pulse = heartBeat(t);
  const hit = arrive > 0 ? Math.exp(-(t - arrive) * 3) : 0;
  const s = (92 + 30 * hit) * (1 + pulse);
  const bob = Math.sin(t * 1.4) * 5;
  glow(ctx, HEART.x, HEART.y + bob, 170 + 120 * hit, C.red, (0.45 + 0.5 * hit) * show);
  ctx.save();
  ctx.globalAlpha *= show;
  I.heart(ctx, HEART.x, HEART.y + bob, s, '#d8283a', { veins: true });
  ctx.restore();
  if (arrive > 0) {
    for (let j = 0; j < 3; j++) ring(ctx, HEART.x, HEART.y, clamp((t - arrive - j * 0.16) / 1.1), { r0: 40, r1: 260 + j * 60, color: j ? C.gold : '#ff8a7a', width: 3 - j * 0.6 });
  }
}

export default {
  id: 's01',
  num: '01',
  file: '01-intro',
  title: '片头',
  duration: 10,
  draw(ctx, t) {
    const climbStart = 1.7, climbDur = 3.0;
    const c = p(t, climbStart, climbDur, ease.inOutSine) * NODES.length;
    const arrive = t >= climbStart + climbDur ? climbStart + climbDur : -1;

    // A soft column of light behind the tower.
    glow(ctx, TX, 560, 520, C.violet, 0.16 * p(t, 0, 2), 0.7, 1.3);
    const cp = climbPos(c);
    drawTower(ctx, t, t > climbStart ? cp.y : H);
    drawPath(ctx, t, c);
    // travelled part of the path in solid gold
    if (c > 0) {
      ctx.save();
      ctx.strokeStyle = rgba(C.gold, 0.85);
      ctx.lineWidth = 3;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.shadowColor = rgba(C.gold, 0.7);
      ctx.shadowBlur = 10;
      ctx.beginPath();
      const last = Math.min(NODES.length - 1, Math.floor(c));
      for (let i = 0; i <= last; i++) {
        const q = nodePos(i);
        i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y);
      }
      if (c < NODES.length) ctx.lineTo(cp.x, cp.y);
      ctx.stroke();
      ctx.restore();
      // redraw the passed nodes on top of the gold line
      NODES.forEach(([kind], i) => {
        if (i > c) return;
        const q = nodePos(i);
        I.mapNode(ctx, q.x, q.y, kind === 'boss' ? 25 : 21, kind, { active: Math.max(0.35, 1 - (c - i) * 0.5) });
      });
    }

    // Keys fly from their node to orbit the Heart.
    KEYS.forEach((kk) => {
      const passK = clamp((c - kk.node) / 1.6);
      if (c < kk.node) return;
      const from = nodePos(kk.node);
      const orbitR = 96;
      const ang = kk.angle + t * 0.35;
      const to = { x: HEART.x + Math.cos(ang) * orbitR, y: HEART.y + Math.sin(ang) * orbitR * 0.55 };
      const f = ease.inOutCubic(passK);
      const x = lerp(from.x, to.x, f) + Math.sin(f * Math.PI) * 90 * (kk.node % 2 ? -1 : 1);
      const y = lerp(from.y, to.y, f);
      glow(ctx, x, y, 40, kk.color, 0.65);
      I.key(ctx, x, y, 34, kk.color, { rot: -Math.PI / 4 + f * TAU * 0.5 });
    });

    // Climbing light with a short trail.
    if (t > climbStart - 0.2 && c < NODES.length + 0.2) {
      for (let j = 8; j >= 0; j--) {
        const cc = Math.max(0, c - j * 0.06);
        const q = climbPos(cc);
        const a = (1 - j / 9) * p(t, climbStart - 0.3, 0.3);
        glow(ctx, q.x, q.y, 26 - j * 1.6, j ? C.gold : '#fff2c8', a * (j ? 0.45 : 1));
      }
    }
    drawHeart(ctx, t, arrive);

    // Title block.
    const X = 150;
    text(ctx, 'STS-IRONCLAD-AGENT', X, 380, { size: 24, weight: 600, fam: 'mono', color: C.gold, ls: 8, alpha: p(t, 3.4, 0.8) });
    textReveal(ctx, '让 AI 攀登', X, 520, p(t, 3.7, 1.1), { size: 116, weight: 900, fam: 'serif', color: C.ink, spread: 0.45 });
    // Second line in gold gradient.
    const k2 = p(t, 4.25, 1.1);
    if (k2 > 0) {
      ctx.save();
      const w2 = measure(ctx, '杀戮尖塔', 128, 900, 'serif', 10);
      glow(ctx, X + w2 / 2, 620, 300, C.gold, 0.18 * k2, 1.4, 0.5);
      textReveal(ctx, '杀戮尖塔', X, 668, k2, { size: 128, weight: 900, fam: 'serif', color: '#f6cf74', ls: 10, spread: 0.45, shadow: rgba(C.gold, 0.45), shadowBlur: 24 });
      ctx.restore();
    }
    const ks = p(t, 5.2, 0.9);
    text(ctx, '进阶 20 · 铁甲战士 · 集齐三把钥匙 · 击败心脏', X + (1 - ks) * -20, 760, { size: 34, weight: 500, color: C.sub, alpha: ks });

    const chips = [
      ['局外选择：冻结的神经网络', C.cyan, I.brain],
      ['战斗出牌：模拟器搜索', C.red, I.tree],
      ['真实游戏里验证', C.gold, I.monitor],
    ];
    let cx = X;
    chips.forEach(([label, col, icon], i) => {
      const k = p(t, 6.0 + i * 0.22, 0.6, ease.outBack);
      const w = chip(ctx, cx, 850 + (1 - clamp(k)) * 16, label, { color: col, icon, size: 24, alpha: clamp(k) });
      cx += w + 16;
    });
  },
};
