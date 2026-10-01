// 08 蒸馏 + 学生反馈训练: the student first imitates the teacher's choices, then
// plays on its own while the teacher labels the states it reaches (two rounds).
import { C, p, ease, clamp, lerp, rgba, text, glow, chapter, hash, TAU, chip, ring, rr, bez, flow } from '../engine.js';
import * as I from '../icons.js';
import { teacherCrest, netLayout, network, fmt } from '../widgets.js';

const T = { x: 330, y: 500 };
const D = { x: 960, y: 500 };
const S = { x: 1600, y: 500 };
const NET = netLayout(S.x - 150, S.y - 120, 300, 240, [5, 8, 8, 1]);
const STRIP_Y = 800, STRIP_X0 = 700, STRIP_DX = 190;
const ROUND1 = { t0: 9.8, wrong: [1, 4] };
const ROUND2 = { t0: 15.0, wrong: [3] };

function sampleGlyph(ctx, x, y, col, a = 1, s = 1) {
  ctx.save();
  ctx.globalAlpha *= a;
  ctx.translate(x, y);
  ctx.scale(s, s);
  rr(ctx, -30, -19, 60, 38, 7);
  ctx.fillStyle = rgba('#191730', 0.95);
  ctx.fill();
  ctx.strokeStyle = rgba(col, 0.9);
  ctx.lineWidth = 1.5;
  ctx.stroke();
  for (let i = 0; i < 4; i++) {
    ctx.fillStyle = rgba(C.cyan, 0.4 + 0.15 * i);
    ctx.fillRect(-22 + i * 7, 6 - (6 + i * 3), 4, 6 + i * 3);
  }
  I.check(ctx, 14, 0, 16, col);
  ctx.restore();
}

function dataset(ctx, x, y, n, a) {
  const layers = Math.min(9, 2 + Math.floor(n / 600));
  ctx.save();
  ctx.globalAlpha *= a;
  for (let i = layers - 1; i >= 0; i--) {
    rr(ctx, x - 110 + i * 3, y - 70 - i * 6, 220, 140, 14);
    ctx.fillStyle = i ? 'rgba(30,28,52,0.95)' : 'rgba(40,37,70,0.98)';
    ctx.fill();
    ctx.strokeStyle = rgba(C.gold, i ? 0.18 : 0.5);
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
  for (let r = 0; r < 4; r++) {
    for (let c = 0; c < 6; c++) {
      ctx.fillStyle = rgba(c < 4 ? C.cyan : C.gold, 0.25 + 0.5 * hash(r, c));
      ctx.fillRect(x - 86 + c * 30, y - 46 + r * 26, 24, 14);
    }
  }
  ctx.restore();
}

function roundStrip(ctx, t, R, label) {
  const { t0, wrong } = R;
  const a = p(t, t0, 0.4) * (1 - p(t, t0 + 4.9, 0.4));
  if (a <= 0) return [];
  const pts = Array.from({ length: 6 }, (_, i) => ({ x: STRIP_X0 + i * STRIP_DX, y: STRIP_Y }));
  text(ctx, label, STRIP_X0 - 60, STRIP_Y - 104, { size: 20, weight: 700, color: C.cyan, alpha: a });
  // student's own path
  const pk = p(t, t0 + 0.2, 1.6, ease.inOutQuad);
  ctx.save();
  ctx.globalAlpha *= a;
  ctx.strokeStyle = rgba(C.cyan, 0.7);
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(pts[0].x - 60, STRIP_Y);
  ctx.lineTo(lerp(pts[0].x - 60, pts[5].x, pk), STRIP_Y);
  ctx.stroke();
  ctx.restore();
  const out = [];
  pts.forEach((q, i) => {
    const appear = p(t, t0 + 0.3 + i * 0.27, 0.35, ease.outBack);
    if (appear <= 0) return;
    // teacher check
    const tc = t0 + 1.5 + i * 0.28;
    const ck = p(t, tc, 0.35);
    const isWrong = wrong.includes(i);
    ctx.save();
    ctx.globalAlpha *= a;
    ctx.translate(q.x, q.y);
    ctx.scale(appear, appear);
    ctx.beginPath();
    ctx.arc(0, 0, 20, 0, TAU);
    ctx.fillStyle = '#16152a';
    ctx.fill();
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = ck > 0 ? (isWrong ? C.red : C.green) : C.cyan;
    ctx.stroke();
    text(ctx, 'ABCDAB'[i], 0, 7, { size: 18, weight: 700, fam: 'mono', align: 'center', color: C.cyan });
    ctx.restore();
    text(ctx, '学生选', q.x, q.y + 46, { size: 14, color: C.dim, align: 'center', alpha: a * clamp(appear) });
    // teacher beam (from the crest)
    const bk = p(t, tc - 0.25, 0.3);
    const bf = 1 - p(t, tc + 0.4, 0.3);
    if (bk > 0 && bf > 0) {
      const P = [{ x: T.x + 110, y: T.y + 60 }, { x: T.x + 240, y: STRIP_Y - 30 }, { x: q.x - 90, y: STRIP_Y - 40 }, { x: q.x, y: q.y - 24 }];
      flow(ctx, P, bk, t, { color: C.gold, alpha: a * bf, dots: 2, speed: 2, width: 1.8 });
    }
    if (ck > 0) {
      const k = ease.outBack(ck);
      if (isWrong) {
        chip(ctx, q.x, q.y - 50 - 8 * k, `老师：选 ${'BADCBA'[i]}`, { color: C.gold, size: 16, align: 'center', alpha: a * clamp(ck), weight: 700 });
        ring(ctx, q.x, q.y, clamp((t - tc) / 0.6), { r0: 20, r1: 52, color: C.red });
      } else {
        I.check(ctx, q.x, q.y - 44, 22 * k, C.green);
      }
    }
    out.push({ x: q.x, y: q.y, t: t0 + 3.4 + i * 0.08 });
  });
  return out;
}

export default {
  id: 's08',
  num: '08',
  file: '08-distill',
  title: '蒸馏：把老师教给小网络',
  duration: 22.5,
  draw(ctx, t) {
    chapter(ctx, t, { num: '08', title: '蒸馏：把老师教给小网络', sub: '先模仿老师的选择；再让学生自己打，老师在旁边批改' });

    // stage label (top right)
    const st1 = p(t, 2.6, 0.5) * (1 - p(t, 9.3, 0.4));
    const st2 = p(t, 9.7, 0.5);
    chip(ctx, 1800, 200, '第一步 · 模仿老师的选择', { color: C.gold, size: 22, align: 'right', alpha: st1, weight: 700 });
    chip(ctx, 1800, 200, '第二步 · 学生自己打，老师批改（DAgger）', { color: C.cyan, size: 22, align: 'right', alpha: st2, weight: 700 });

    // ---- teacher
    teacherCrest(ctx, T.x, T.y - 20, 80, p(t, 2.1, 0.8), t);
    const ta = p(t, 2.5, 0.5);
    text(ctx, '老师：复杂、更强', T.x, T.y + 120, { size: 22, weight: 700, color: C.gold, align: 'center', alpha: ta });
    const games = Math.round(3000 * ease.inOutQuad(clamp((t - 2.8) / 5.0)));
    text(ctx, `老师对局 ${fmt(games)} 局`, T.x, T.y + 152, { size: 18, fam: 'mono', color: C.sub, align: 'center', alpha: ta });

    // ---- dataset
    let n = Math.round(lerp(0, 3000, ease.inOutQuad(clamp((t - 3.0) / 5.0))));
    if (t > ROUND1.t0 + 3.4) n += Math.round(600 * p(t, ROUND1.t0 + 3.4, 0.8));
    if (t > ROUND2.t0 + 3.4) n += Math.round(600 * p(t, ROUND2.t0 + 3.4, 0.8));
    const dA = p(t, 2.5, 0.6);
    dataset(ctx, D.x, D.y, n, dA);
    text(ctx, '训练题库', D.x, D.y + 110, { size: 22, weight: 700, align: 'center', alpha: dA });
    text(ctx, '局面 → 老师的选择', D.x, D.y + 140, { size: 17, color: C.sub, align: 'center', alpha: dA });
    if (t > ROUND1.t0 + 3.6) chip(ctx, D.x, D.y - 118, '+ 学生自己走到的局面', { color: C.cyan, size: 17, align: 'center', alpha: p(t, ROUND1.t0 + 3.6, 0.4) });

    // teacher → dataset samples
    const P1 = [{ x: T.x + 100, y: T.y - 40 }, { x: T.x + 260, y: T.y - 170 }, { x: D.x - 260, y: D.y - 170 }, { x: D.x - 120, y: D.y - 40 }];
    const s1a = p(t, 2.8, 0.4) * (1 - p(t, 8.2, 0.5));
    if (s1a > 0) {
      for (let i = 0; i < 5; i++) {
        const k = ((t - 2.8) * 0.55 + i / 5) % 1;
        const q = bez(P1, ease.inOutSine(k));
        sampleGlyph(ctx, q.x, q.y, C.gold, s1a * Math.sin(k * Math.PI), 0.9);
      }
    }
    // dataset → student training flow
    const trainOn = (t > 3.6 && t < 8.6) || (t > ROUND1.t0 + 4.0 && t < ROUND1.t0 + 5.3) || (t > ROUND2.t0 + 4.0 && t < ROUND2.t0 + 5.3);
    const P2 = [{ x: D.x + 120, y: D.y - 40 }, { x: D.x + 260, y: D.y - 170 }, { x: S.x - 300, y: S.y - 170 }, { x: S.x - 170, y: S.y - 40 }];
    const s2a = clamp(p(t, 3.6, 0.4)) * (trainOn ? 1 : 0);
    if (s2a > 0) {
      for (let i = 0; i < 5; i++) {
        const k = ((t - 3.6) * 0.6 + i / 5) % 1;
        const q = bez(P2, ease.inOutSine(k));
        sampleGlyph(ctx, q.x, q.y, C.cyan, s2a * Math.sin(k * Math.PI), 0.9);
      }
    }

    // ---- student
    const sa = p(t, 2.4, 0.8);
    const learn = clamp((t - 3.6) / 5.0) * 0.6 + p(t, ROUND1.t0 + 4.0, 1.3) * 0.25 + p(t, ROUND2.t0 + 4.0, 1.3) * 0.15;
    glow(ctx, S.x, S.y, 260, C.cyan, 0.08 + 0.18 * learn);
    network(ctx, NET, { k: sa, t, color: C.cyan, pulse: trainOn ? 1 : 0.3, act: trainOn ? (t * 0.8) % 1 : -1, edgeA: 0.6 + learn });
    text(ctx, '学生：一个小网络', S.x, S.y + 158, { size: 22, weight: 700, color: C.cyan, align: 'center', alpha: sa });
    // similarity meter
    const ma = p(t, 4.0, 0.5);
    ctx.save();
    ctx.globalAlpha *= ma;
    text(ctx, '和老师的选择越来越像', S.x, S.y + 192, { size: 16, color: C.sub, align: 'center' });
    rr(ctx, S.x - 120, S.y + 204, 240, 10, 5);
    ctx.fillStyle = 'rgba(255,255,255,0.08)';
    ctx.fill();
    rr(ctx, S.x - 120, S.y + 204, 240 * (0.15 + 0.8 * learn), 10, 5);
    const g = ctx.createLinearGradient(S.x - 120, 0, S.x + 120, 0);
    g.addColorStop(0, rgba(C.cyan, 0.5));
    g.addColorStop(1, C.gold);
    ctx.fillStyle = g;
    ctx.fill();
    ctx.restore();

    // round counter
    const rk = p(t, ROUND1.t0 + 0.2, 0.4);
    if (rk > 0) {
      const round = t >= ROUND2.t0 ? 2 : 1;
      const spin = p(t, ROUND2.t0 - 0.2, 0.6, ease.inOutCubic);
      ctx.save();
      ctx.globalAlpha *= rk;
      ctx.translate(S.x + 190, S.y - 150);
      ctx.rotate(spin * TAU);
      I.loop(ctx, 0, 0, 40, C.cyan);
      ctx.restore();
      text(ctx, `第 ${round} 轮`, S.x + 220, S.y - 140, { size: 22, weight: 700, color: C.cyan, alpha: rk });
    }

    // ---- student plays, teacher labels
    const out1 = roundStrip(ctx, t, ROUND1, '第 1 轮：学生自己打一局');
    const out2 = roundStrip(ctx, t, ROUND2, '第 2 轮：错得更少');
    [...out1, ...out2].forEach((o) => {
      const k = p(t, o.t, 0.7, ease.inOutCubic);
      if (k <= 0 || k >= 1) return;
      const x = lerp(o.x, D.x, k), y = lerp(o.y, D.y + 60, k) - Math.sin(k * Math.PI) * 80;
      sampleGlyph(ctx, x, y, C.gold, Math.sin(k * Math.PI), 0.7);
    });

    // ---- conclusion
    const ck = p(t, 20.1, 0.6);
    text(ctx, '学生学的是老师的"选择"，不需要老师那一整套拼装', 960, 920, { size: 26, weight: 500, color: C.sub, align: 'center', alpha: ck });
    const pre = p(t, 8.0, 0.5) * (1 - p(t, ROUND1.t0 + 0.2, 0.4));
    text(ctx, '只模仿还不够：学生一犯错，就会走到老师没去过的局面', 960, 900, { size: 26, weight: 500, color: C.sub, align: 'center', alpha: pre });
  },
};
