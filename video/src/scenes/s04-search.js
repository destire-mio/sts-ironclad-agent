// 04 出牌分支搜索与结果回传: a search tree over card plays. Each iteration walks
// down a branch, plays the fight out to the end, and sends the result back up.
import { C, p, ease, clamp, lerp, rgba, text, glow, panel, chapter, hash, TAU, ring, chip, mix } from '../engine.js';
import * as I from '../icons.js';
import { card, CARDS, hpBar, ironclad, monster, fmt } from '../widgets.js';

const ROOT = { id: 'R', x: 1250, y: 292, label: '现在' };
const L1 = [
  { id: 'A', x: 850, card: CARDS.bash, label: '痛击', final: [0.71, 14200] },
  { id: 'B', x: 1110, card: CARDS.strike, label: '打击', final: [0.38, 5100] },
  { id: 'C', x: 1390, card: CARDS.defend, label: '防御', final: [0.55, 8300] },
  { id: 'D', x: 1650, card: CARDS.inflame, label: '燃烧', final: [0.46, 4400] },
].map((n) => ({ ...n, y: 432 }));
const L2 = [];
const L2_LABELS = { A: ['打击', '防御'], B: ['痛击', '防御'], C: ['痛击', '打击'], D: ['痛击', '打击'] };
L1.forEach((n) => L2_LABELS[n.id].forEach((lb, i) => L2.push({ id: `${n.id}${i + 1}`, parent: n.id, x: n.x + (i ? 64 : -64), y: 584, label: lb })));
const L3 = [];
L2.forEach((n) => [0, 1].forEach((i) => L3.push({ id: `${n.id}${i}`, parent: n.id, x: n.x + (i ? 26 : -26), y: 694 })));
const NODES = Object.fromEntries([ROOT, ...L1, ...L2, ...L3].map((n) => [n.id, n]));

const ITERS = [
  { path: ['R', 'A', 'A1'], win: true, hp: 38 },
  { path: ['R', 'B', 'B1'], win: false },
  { path: ['R', 'C', 'C1'], win: true, hp: 22 },
  { path: ['R', 'D', 'D1'], win: false },
  { path: ['R', 'A', 'A2'], win: true, hp: 45 },
];
const IT0 = 2.9, ITD = 1.5;
const FAST0 = IT0 + ITERS.length * ITD + 0.1; // 10.5
const FAST1 = 13.7;
const DECIDE = 13.9;

function phaseOf(t) {
  const k = (t - IT0) / ITD;
  const i = Math.floor(k);
  if (i < 0 || i >= ITERS.length) return null;
  return { i, u: (k - i) * ITD };
}

// Stats after the explicit iterations up to time t: {id: [wins, visits]}
function explicitStats(t) {
  const st = {};
  ITERS.forEach((it, i) => {
    const start = IT0 + i * ITD;
    it.path.forEach((id, depth) => {
      // backprop passes leaf first, root last, between 0.85 and 1.3
      const pass = start + 0.85 + ((it.path.length - 1 - depth) / (it.path.length - 1)) * 0.45;
      if (t >= pass) {
        const s = (st[id] ??= [0, 0]);
        s[1] += 1;
        if (it.win) s[0] += 1;
      }
    });
  });
  return st;
}

function rolloutPts(leaf, seed) {
  const pts = [{ x: leaf.x, y: leaf.y }];
  let x = leaf.x;
  for (let i = 1; i <= 9; i++) {
    x += (hash(seed, i) - 0.5) * 36;
    pts.push({ x, y: lerp(leaf.y, 846, i / 9) });
  }
  return pts;
}

function polyline(ctx, pts, k, color, width) {
  const n = pts.length - 1;
  const upto = k * n;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i <= n; i++) {
    if (i <= upto) ctx.lineTo(pts[i].x, pts[i].y);
    else {
      const f = upto - (i - 1);
      if (f > 0) ctx.lineTo(lerp(pts[i - 1].x, pts[i].x, f), lerp(pts[i - 1].y, pts[i].y, f));
      break;
    }
  }
  ctx.stroke();
  ctx.restore();
  const f = Math.min(n, upto);
  const i0 = Math.floor(f), fr = f - i0;
  const a = pts[i0], b = pts[Math.min(n, i0 + 1)];
  return { x: lerp(a.x, b.x, fr), y: lerp(a.y, b.y, fr) };
}

function edge(ctx, a, b, color, width, alpha = 1) {
  ctx.save();
  ctx.globalAlpha *= alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(a.x, a.y);
  const my = (a.y + b.y) / 2;
  ctx.bezierCurveTo(a.x, my, b.x, my, b.x, b.y);
  ctx.stroke();
  ctx.restore();
}

function edgePoint(a, b, k) {
  const my = (a.y + b.y) / 2;
  const u = 1 - k;
  return {
    x: u * u * u * a.x + 3 * u * u * k * a.x + 3 * u * k * k * b.x + k * k * k * b.x,
    y: u * u * u * a.y + 3 * u * u * k * my + 3 * u * k * k * my + k * k * k * b.y,
  };
}

export default {
  id: 's04',
  num: '04',
  file: '04-search',
  title: '出牌：分支搜索与结果回传',
  duration: 19,
  draw(ctx, t) {
    chapter(ctx, t, { num: '04', title: '出牌：分支搜索与结果回传', sub: '把每种出牌顺序都在模拟器里试着打完，再看哪一步最好' });

    const ph = phaseOf(t);
    const fastK = clamp((t - FAST0) / (FAST1 - FAST0));
    const decided = p(t, DECIDE, 0.6);
    const est = explicitStats(t);

    // ---- step chips
    const steps = ['① 沿一条分支往下走', '② 推演到战斗结束', '③ 把输赢传回上面'];
    let sx = 1010;
    steps.forEach((s, i) => {
      const a = p(t, 2.4 + i * 0.12, 0.5);
      let on = 0;
      if (ph) on = i === 0 ? (ph.u < 0.42 ? 1 : 0) : i === 1 ? (ph.u >= 0.42 && ph.u < 0.85 ? 1 : 0) : ph.u >= 0.85 ? 1 : 0;
      if (t >= FAST0 && t < FAST1) on = 0.6;
      const col = on > 0 ? C.red : C.sub;
      const w = chip(ctx, sx, 200, s, { color: col, size: 21, alpha: a * (on ? 1 : 0.55), fill: rgba(col, on ? 0.18 : 0.06), weight: on ? 700 : 500 });
      sx += w + 14;
    });

    // ---- battle panel
    const pa = p(t, 2.0, 0.7);
    const BP = { x: 110, y: 262, w: 540, h: 632 };
    panel(ctx, BP.x, BP.y + (1 - pa) * 24, BP.w, BP.h, { alpha: pa, accent: C.red });
    ctx.save();
    ctx.globalAlpha *= pa;
    text(ctx, '当前战斗', BP.x + 30, BP.y + 54, { size: 26, weight: 700 });
    text(ctx, '第 12 层 · 我方回合', BP.x + BP.w - 30, BP.y + 54, { size: 18, color: C.sub, align: 'right' });
    ironclad(ctx, BP.x + 120, BP.y + 200, 120);
    hpBar(ctx, BP.x + 50, BP.y + 290, 140, 54, 80, { h: 18 });
    // monster takes the hit at the end
    const hitT = DECIDE + 1.3;
    const hit = t >= hitT ? Math.exp(-(t - hitT) * 5) : 0;
    const mhp = t >= hitT ? 54 : 62;
    monster(ctx, BP.x + 400 + Math.sin(t * 60) * 8 * hit, BP.y + 192, 160, { t, color: '#8a4a9e' });
    if (hit > 0) glow(ctx, BP.x + 400, BP.y + 192, 160, '#ffffff', hit * 0.8);
    hpBar(ctx, BP.x + 330, BP.y + 290, 140, mhp, 62, { h: 18 });
    I.sword(ctx, BP.x + 380, BP.y + 84, 28, C.red);
    text(ctx, '18', BP.x + 402, BP.y + 94, { size: 26, weight: 900, fam: 'mono', color: C.red });
    if (t >= hitT) {
      const dk = clamp((t - hitT) / 1.2);
      text(ctx, '-8', BP.x + 470, BP.y + 150 - dk * 50, { size: 44, weight: 900, fam: 'mono', color: '#ffd166', alpha: 1 - dk * 0.6, stroke: '#3a0a0a', strokeWidth: 6 });
      chip(ctx, BP.x + 400, BP.y + 340, '易伤', { color: C.violet, size: 18, align: 'center', alpha: p(t, hitT + 0.1, 0.4) });
    }
    // energy orb
    const ex = BP.x + 70, ey = BP.y + 396;
    glow(ctx, ex, ey, 60, C.orange, 0.35);
    ctx.beginPath();
    ctx.arc(ex, ey, 32, 0, TAU);
    const og = ctx.createRadialGradient(ex - 8, ey - 10, 4, ex, ey, 32);
    og.addColorStop(0, '#ffc07a');
    og.addColorStop(0.7, '#e2502e');
    og.addColorStop(1, '#6a160e');
    ctx.fillStyle = og;
    ctx.fill();
    text(ctx, t >= hitT ? '1/3' : '3/3', ex, ey + 9, { size: 24, weight: 900, fam: 'mono', align: 'center', color: '#fff' });
    text(ctx, '能量', ex + 50, ey + 8, { size: 20, color: C.sub });
    text(ctx, '手牌', BP.x + 30, BP.y + 466, { size: 20, color: C.sub });
    ctx.restore();

    // hand
    L1.forEach((n, j) => {
      const baseX = BP.x + 118 + j * 104, baseY = BP.y + 548;
      let x = baseX, y = baseY, rot = (j - 1.5) * 0.06, sc = 0.66, a = pa;
      let glowK = 0;
      if (j === 0) {
        const lift = p(t, DECIDE + 0.2, 0.4);
        const fly = p(t, DECIDE + 0.7, 0.6, ease.inCubic);
        glowK = lift;
        y -= 34 * lift;
        x = lerp(x, BP.x + 400, fly);
        y = lerp(y, BP.y + 192, fly);
        rot = lerp(rot, -0.4, fly);
        sc = lerp(0.66, 0.3, fly);
        a *= 1 - p(t, DECIDE + 1.25, 0.1);
      }
      const dimK = decided * (j === 0 ? 0 : 0.5);
      card(ctx, x, y, n.card, { scale: sc, rot, alpha: a, glow: glowK, glowColor: C.gold, dim: dimK });
    });

    // ---- tree edges
    const treeA = p(t, 2.3, 0.6);
    const visible = new Set(['R', 'A', 'B', 'C', 'D']);
    ITERS.forEach((it, i) => {
      if (t >= IT0 + i * ITD + 0.3) it.path.forEach((id) => visible.add(id));
    });
    if (t >= FAST0) {
      L2.forEach((n) => { if (t >= FAST0 + hash(n.x) * 1.2) visible.add(n.id); });
      L3.forEach((n) => { if (t >= FAST0 + 0.4 + hash(n.x, 3) * 2.0) visible.add(n.id); });
    }
    const bestPath = new Set(['R', 'A']);
    const allNodes = [...L1, ...L2, ...L3];
    allNodes.forEach((n) => {
      if (!visible.has(n.id)) return;
      const par = NODES[n.parent ?? 'R'];
      const gold = decided > 0 && bestPath.has(n.id);
      const appear = n.parent ? 1 : treeA;
      edge(ctx, par, n, gold ? rgba(C.gold, 0.9) : rgba(C.red, 0.32), gold ? 3.5 : 1.6, appear);
    });

    // ---- explicit iteration animation
    if (ph) {
      const it = ITERS[ph.i];
      const nodes = it.path.map((id) => NODES[id]);
      const u = ph.u;
      // 1. selection light descends
      if (u < 0.5) {
        const k = clamp(u / 0.4);
        const segs = nodes.length - 1;
        const s = Math.min(segs - 1, Math.floor(k * segs));
        const f = k * segs - s;
        for (let j = 0; j <= s; j++) {
          const kk = j < s ? 1 : f;
          for (let q = 0; q <= 10; q++) {
            if (q / 10 > kk) break;
            const pt = edgePoint(nodes[j], nodes[j + 1], q / 10);
            glow(ctx, pt.x, pt.y, 10, C.red, 0.35);
          }
        }
        const head = edgePoint(nodes[s], nodes[s + 1], f);
        glow(ctx, head.x, head.y, 30, '#ffd2c8', 0.9);
      }
      // 2. rollout
      const leaf = nodes.at(-1);
      const pts = rolloutPts(leaf, ph.i + 1);
      const rk = clamp((u - 0.42) / 0.38);
      const fadeR = 1 - clamp((u - 1.25) / 0.25);
      if (rk > 0) {
        const head = polyline(ctx, pts, ease.inOutQuad(rk), rgba(rk >= 1 ? (it.win ? C.green : C.red) : '#ffffff', 0.75 * fadeR), 2);
        if (rk < 1) glow(ctx, head.x, head.y, 22, '#ffffff', 0.8);
        if (rk >= 1) {
          const bk = ease.outBack(clamp((u - 0.8) / 0.25));
          const end = pts.at(-1);
          ctx.save();
          ctx.globalAlpha *= fadeR;
          ctx.translate(end.x, end.y + 26);
          ctx.scale(bk, bk);
          chip(ctx, 0, 0, it.win ? `胜 · 剩 ${it.hp} 血` : '败', { color: it.win ? C.green : C.red, size: 20, align: 'center', weight: 700, fill: rgba(it.win ? C.green : C.red, 0.2) });
          ctx.restore();
          if (u < 1.1) text(ctx, '战斗结束', end.x + 16, end.y - 6, { size: 15, color: C.sub, alpha: fadeR * 0.8 });
        }
      }
      // 3. backprop pulse up the path
      const bk = clamp((u - 0.85) / 0.45);
      if (bk > 0 && bk < 1) {
        const segs = nodes.length - 1;
        const kk = bk * segs;
        const s = Math.min(segs - 1, Math.floor(kk));
        const f = kk - s;
        const a = nodes[segs - s], b = nodes[segs - s - 1];
        const pt = edgePoint(b, a, 1 - f);
        const col = it.win ? C.green : C.red;
        glow(ctx, pt.x, pt.y, 36, col, 1);
        glow(ctx, pt.x, pt.y, 12, '#ffffff', 0.9);
      }
      nodes.forEach((n, depth) => {
        const pass = 0.85 + ((nodes.length - 1 - depth) / (nodes.length - 1)) * 0.45;
        ring(ctx, n.x, n.y, clamp((u - pass) / 0.5), { r0: 12, r1: 48, color: it.win ? C.green : C.red, width: 2.5 });
      });
    }

    // ---- fast phase: many quick iterations
    if (t >= FAST0 && t < FAST1 + 0.2) {
      const slot = Math.floor((t - FAST0) / 0.09);
      for (let k = 0; k < 3; k++) {
        const sid = slot * 3 + k;
        const leaf = L3[Math.floor(hash(sid, 9) * L3.length)];
        if (!visible.has(leaf.id)) continue;
        const lp = NODES[leaf.parent], l1 = NODES[lp.parent];
        const win = hash(sid, 4) < (l1.final[0]);
        const local = ((t - FAST0) % 0.09) / 0.09;
        const col = win ? C.green : C.red;
        const a = 0.5 * (1 - local);
        edge(ctx, ROOT, l1, rgba(col, 0.8), 2, a);
        edge(ctx, l1, lp, rgba(col, 0.8), 2, a);
        edge(ctx, lp, leaf, rgba(col, 0.8), 2, a);
        ctx.save();
        ctx.globalAlpha *= a;
        ctx.strokeStyle = col;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(leaf.x, leaf.y);
        ctx.lineTo(leaf.x + (hash(sid, 5) - 0.5) * 30, 820);
        ctx.stroke();
        ctx.restore();
      }
    }

    // ---- nodes + stats
    const totalSims = t < FAST0 ? (est.R?.[1] ?? 0) : Math.round(lerp(5, 32000, ease.inCubic(fastK)));
    ctx.save();
    ctx.globalAlpha *= treeA;
    allNodes.forEach((n) => {
      if (!visible.has(n.id)) return;
      const s = est[n.id] ?? [0, 0];
      const isL1 = n.y === 432;
      let wr = s[1] ? s[0] / s[1] : null;
      let visits = s[1];
      if (isL1 && t >= FAST0) {
        const f = ease.inCubic(fastK);
        wr = lerp(wr ?? 0.5, n.final[0], f);
        visits = Math.round(lerp(s[1], n.final[1], f));
      }
      const share = isL1 && t >= FAST0 ? n.final[1] / 32000 : 0;
      const r = isL1 ? 15 + 10 * Math.sqrt(share) * ease.inCubic(fastK) : n.y === 584 ? 10 : 6;
      const gold = decided > 0 && bestPath.has(n.id);
      const colr = wr === null ? C.dim : mix(C.red, C.green, clamp((wr - 0.3) / 0.5));
      if (gold) glow(ctx, n.x, n.y, 60, C.gold, 0.6 * decided);
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, TAU);
      ctx.fillStyle = gold ? mix('#1a1526', C.gold, 0.5) : '#1a1828';
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = gold ? C.gold : rgba(C.red, 0.85);
      ctx.stroke();
      if (wr !== null && n.y !== 694) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 5, -Math.PI / 2, -Math.PI / 2 + TAU * wr);
        ctx.strokeStyle = colr;
        ctx.lineWidth = 4;
        ctx.stroke();
      }
      if (isL1) {
        text(ctx, n.label, n.x, n.y - r - 18, { size: 24, weight: 700, align: 'center', color: gold ? C.gold : C.ink, alpha: treeA });
        if (visits > 0) {
          text(ctx, `胜率 ${Math.round(wr * 100)}%`, n.x + 42, n.y - 3, { size: 18, weight: 700, color: colr });
          text(ctx, `试 ${fmt(visits)} 次`, n.x + 42, n.y + 21, { size: 16, fam: 'mono', color: C.sub });
        }
      } else if (n.y === 584) {
        text(ctx, n.label, n.x + 16, n.y - 14, { size: 15, color: C.sub });
      }
    });
    ctx.restore();
    // root
    glow(ctx, ROOT.x, ROOT.y, 50, C.red, 0.4 * treeA);
    ctx.beginPath();
    ctx.arc(ROOT.x, ROOT.y, 22 * ease.outBack(treeA), 0, TAU);
    ctx.fillStyle = '#2a1820';
    ctx.fill();
    ctx.lineWidth = 3;
    ctx.strokeStyle = C.red;
    ctx.stroke();
    text(ctx, '现在', ROOT.x, ROOT.y + 8, { size: 18, weight: 700, align: 'center', alpha: treeA });
    text(ctx, `已推演 ${fmt(totalSims)} 局`, ROOT.x + 46, ROOT.y + 8, { size: 22, weight: 700, fam: 'mono', color: t >= FAST0 ? C.gold : C.ink, alpha: treeA });

    text(ctx, '胜率为示意', 1790, 760, { size: 15, color: C.dim, align: 'right', alpha: p(t, 4.0, 0.5) });

    // ---- verdict
    const vk = p(t, DECIDE + 0.3, 0.6);
    chip(ctx, 850, 790, '胜率最高的第一步：痛击', { color: C.gold, size: 26, align: 'center', weight: 700, alpha: vk, icon: I.check });
    const ek2 = p(t, DECIDE + 1.9, 0.6);
    text(ctx, '打出这一步，局面变了，再重新搜索下一步', 1250, 880, { size: 26, weight: 500, color: C.sub, align: 'center', alpha: ek2 });
  },
};
