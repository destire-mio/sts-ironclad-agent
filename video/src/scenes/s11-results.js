// 11 评测结果: numbers come from config.js (EVAL). Any `null` value is drawn as a
// placeholder ("XX.X%") with a hatched track, so the layout can be signed off
// before the final numbers are filled in.
import { C, p, ease, rgba, text, glow, panel, chapter, TAU, chip, rr } from '../engine.js';
import * as I from '../icons.js';
import { EVAL } from '../config.js';
import { fmt } from '../widgets.js';

const HERO = { x: 110, y: 262, w: 640, h: 600 };
const ROWS = { x: 790, y: 262, w: 1020, h: 330 };
const STAGES = { x: 790, y: 614, w: 1020, h: 248 };
const COLORS = { gold: C.gold, cyan: C.cyan, red: C.red };

const num = (v, ph = 'XXX') => (v == null ? ph : fmt(v));

let hatchCache = null;
function hatch(ctx) {
  if (!hatchCache) {
    const c = document.createElement('canvas');
    c.width = c.height = 12;
    const g = c.getContext('2d');
    g.strokeStyle = 'rgba(255,255,255,0.16)';
    g.lineWidth = 2;
    g.beginPath();
    g.moveTo(-3, 15);
    g.lineTo(15, -3);
    g.moveTo(-3, 3);
    g.lineTo(3, -3);
    g.moveTo(9, 15);
    g.lineTo(15, 9);
    g.stroke();
    hatchCache = c;
  }
  return ctx.createPattern(hatchCache, 'repeat');
}

function gauge(ctx, cx, cy, r, v, k, t) {
  const lw = 26;
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineWidth = lw;
  ctx.strokeStyle = 'rgba(255,255,255,0.07)';
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, TAU);
  ctx.stroke();
  if (v == null) {
    // placeholder: slow rotating dashed ring
    ctx.setLineDash([6, 16]);
    ctx.lineDashOffset = -t * 30;
    ctx.lineWidth = 3;
    ctx.strokeStyle = rgba(C.gold, 0.55 * k);
    ctx.beginPath();
    ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + TAU * k);
    ctx.stroke();
  } else {
    const a1 = -Math.PI / 2 + TAU * (v / 100) * k;
    const g = ctx.createLinearGradient(cx - r, cy - r, cx + r, cy + r);
    g.addColorStop(0, '#ffe08a');
    g.addColorStop(1, '#e09a2c');
    ctx.strokeStyle = g;
    ctx.beginPath();
    ctx.arc(cx, cy, r, -Math.PI / 2, a1);
    ctx.stroke();
    glow(ctx, cx + Math.cos(a1) * r, cy + Math.sin(a1) * r, 40, C.gold, 0.8 * k);
  }
  ctx.restore();
}

export default {
  id: 's11',
  num: '11',
  file: '11-results',
  title: '评测结果',
  duration: 15,
  draw(ctx, t) {
    chapter(ctx, t, { num: '11', title: '评测结果', sub: '只看能复查的数字：固定种子，从头打到底' });
    let rx = 1810;
    [...EVAL.rules].reverse().forEach((r, i) => {
      const w = chip(ctx, rx, 200, r, { color: C.sub, size: 19, align: 'right', alpha: p(t, 2.0 + (EVAL.rules.length - i) * 0.1, 0.5) });
      rx -= w + 10;
    });

    // ---- hero gauge
    const ha = p(t, 2.0, 0.6);
    panel(ctx, HERO.x, HERO.y + (1 - ha) * 20, HERO.w, HERO.h, { alpha: ha, accent: C.gold, glow: C.gold, glowA: 0.06 });
    const hk = p(t, 2.6, 2.0, ease.inOutCubic);
    const h = EVAL.hero;
    ctx.save();
    ctx.globalAlpha *= ha;
    text(ctx, h.label, HERO.x + HERO.w / 2, HERO.y + 62, { size: 28, weight: 700, align: 'center' });
    const gx = HERO.x + HERO.w / 2, gy = HERO.y + 300;
    gauge(ctx, gx, gy, 170, h.value, hk, t);
    I.heart(ctx, gx, gy - 84, 40, '#d8283a');
    const shown = h.value == null ? 'XX.X%' : `${(h.value * hk).toFixed(1)}%`;
    const pulse = h.value == null ? 0.75 + 0.25 * Math.sin(t * 3) : 1;
    text(ctx, shown, gx, gy + 34, { size: 76, weight: 900, fam: 'serif', align: 'center', color: '#ffe3a3', alpha: pulse });
    text(ctx, '胜率', gx, gy + 78, { size: 20, color: C.sub, align: 'center' });
    text(ctx, `${num(h.games)} 局`, gx, HERO.y + 540, { size: 24, weight: 700, align: 'center', fam: 'sans' });
    text(ctx, `95% 区间 [${h.lo == null ? 'XX.X' : h.lo.toFixed(1)}, ${h.hi == null ? 'XX.X' : h.hi.toFixed(1)}]`, gx, HERO.y + 572, { size: 18, color: C.sub, align: 'center', fam: 'mono' });
    ctx.restore();

    // ---- comparison rows
    const ra = p(t, 2.4, 0.6);
    panel(ctx, ROWS.x, ROWS.y + (1 - ra) * 20, ROWS.w, ROWS.h, { alpha: ra, accent: C.cyan });
    text(ctx, '模拟器 vs 真实游戏 · 心脏胜率', ROWS.x + 32, ROWS.y + 54, { size: 24, weight: 700, alpha: ra });
    const bx = ROWS.x + 280, bw = 470;
    EVAL.rows.forEach((r, i) => {
      const y = ROWS.y + 118 + i * 72;
      const k = p(t, 3.0 + i * 0.35, 1.2, ease.inOutCubic);
      const col = COLORS[r.color] ?? C.cyan;
      ctx.save();
      ctx.globalAlpha *= p(t, 2.8 + i * 0.3, 0.5);
      text(ctx, r.label, ROWS.x + 32, y + 8, { size: 22, weight: 700 });
      chip(ctx, ROWS.x + 150, y, r.who, { color: col, size: 18, padX: 12 });
      rr(ctx, bx, y - 13, bw, 26, 13);
      ctx.fillStyle = 'rgba(255,255,255,0.06)';
      ctx.fill();
      if (r.value == null) {
        rr(ctx, bx, y - 13, bw * k, 26, 13);
        ctx.fillStyle = hatch(ctx);
        ctx.fill();
      } else {
        const fw = bw * (r.value / 100) * k;
        rr(ctx, bx, y - 13, Math.max(26, fw), 26, 13);
        const g = ctx.createLinearGradient(bx, 0, bx + fw, 0);
        g.addColorStop(0, rgba(col, 0.45));
        g.addColorStop(1, col);
        ctx.fillStyle = g;
        ctx.fill();
        glow(ctx, bx + fw, y, 30, col, 0.6 * k);
      }
      text(ctx, r.value == null ? 'XX.X%' : `${(r.value * k).toFixed(1)}%`, bx + bw + 22, y + 11, { size: 30, weight: 700, fam: 'mono', color: r.value == null ? C.sub : col });
      text(ctx, `${num(r.games, 'XXXX')} 局`, bx + bw + 150, y + 9, { size: 17, color: C.dim });
      ctx.restore();
    });

    // ---- stage death rates
    const sa = p(t, 2.8, 0.6);
    panel(ctx, STAGES.x, STAGES.y + (1 - sa) * 20, STAGES.w, STAGES.h, { alpha: sa, accent: C.red });
    text(ctx, '输在哪里 · 各阶段死亡率', STAGES.x + 32, STAGES.y + 50, { size: 24, weight: 700, alpha: sa });
    text(ctx, '按进入该阶段的对局计算', STAGES.x + STAGES.w - 32, STAGES.y + 50, { size: 17, color: C.sub, align: 'right', alpha: sa });
    const n = EVAL.stages.length;
    const cw = (STAGES.w - 64) / n;
    const base = STAGES.y + 196, maxH = 92;
    const maxV = Math.max(25, ...EVAL.stages.map((s) => s.value ?? 0));
    EVAL.stages.forEach((s, i) => {
      const x = STAGES.x + 32 + i * cw + cw / 2;
      const k = p(t, 4.0 + i * 0.12, 0.9, ease.outCubic);
      const hh = s.value == null ? maxH * 0.55 : (s.value / maxV) * maxH;
      ctx.save();
      ctx.globalAlpha *= sa;
      rr(ctx, x - 26, base - hh * k, 52, hh * k, [8, 8, 2, 2]);
      if (s.value == null) {
        ctx.fillStyle = hatch(ctx);
        ctx.fill();
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = 'rgba(255,255,255,0.25)';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      } else {
        const g = ctx.createLinearGradient(0, base - hh, 0, base);
        g.addColorStop(0, s.label === '心脏' ? C.red : '#ff8a72');
        g.addColorStop(1, rgba(C.red, 0.35));
        ctx.fillStyle = g;
        ctx.fill();
      }
      text(ctx, s.value == null ? 'X.X%' : `${s.value.toFixed(1)}%`, x, base - hh * k - 10, { size: 17, weight: 700, fam: 'mono', align: 'center', color: s.value == null ? C.sub : C.ink, alpha: k });
      text(ctx, s.label, x, base + 30, { size: 16, align: 'center', color: C.sub });
      ctx.restore();
    });
  },
};
