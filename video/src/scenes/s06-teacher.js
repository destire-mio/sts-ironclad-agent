// 06 专家规则与对局数据训练: expert rules and measured game data are assembled,
// together with an earlier trained network and combat search, into the teacher.
import { C, p, ease, clamp, lerp, rgba, text, panel, chapter, hash, rr, sCurve, flow, measure } from '../engine.js';
import * as I from '../icons.js';
import { teacherCrest } from '../widgets.js';

const RP = { x: 110, y: 262, w: 640, h: 330 };
const DP = { x: 110, y: 614, w: 640, h: 300 };
const CREST = { x: 1350, y: 588 };
const MODS = [
  { key: 'rules', x: 1100, y: 386, title: '专家规则', desc: '攻略里的选牌、休息规则', color: C.gold, icon: I.book, t: 7.6 },
  { key: 'parent', x: 1600, y: 386, title: '父网络', desc: '早先用对局结果训练的网络', color: C.cyan, icon: I.brain, t: 8.0 },
  { key: 'table', x: 1100, y: 790, title: '价值表', desc: '每张牌在各个关口值多少', color: C.green, icon: grid, t: 8.4 },
  { key: 'search', x: 1600, y: 790, title: '战斗搜索', desc: '出牌仍交给模拟器搜索', color: C.red, icon: I.tree, t: 8.8 },
];
const MW = 300, MH = 112;

const RULES = [
  ['已有两张「耸肩无视」', '第三张不再拿'],
  ['后期的「金属化」', '加分'],
  ['多余的「武装」', '跳过'],
  ['生命低于 75%', '篝火优先休息'],
];
const TABLE_ROWS = ['燃烧', '耸肩无视', '重刃', '祭品'];
const TABLE_COLS = ['精英', '一幕Boss', '二幕Boss', '心脏'];
const LOG = Array.from({ length: 30 }, (_, i) => {
  const seed = 3900012000 + Math.floor(hash(i, 1) * 9000);
  const win = hash(i, 2) > 0.5;
  const floor = win ? 56 : 6 + Math.floor(hash(i, 3) * 49);
  const where = win ? '心脏' : floor > 50 ? '心脏' : floor > 33 ? '第三幕' : floor > 16 ? '第二幕' : '第一幕';
  return { seed, win, floor, where, hp: win ? 3 + Math.floor(hash(i, 4) * 60) : 0 };
});

function grid(ctx, x, y, s, color) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(1.2, s * 0.07);
  const r = s / 2;
  ctx.strokeRect(x - r * 0.85, y - r * 0.7, r * 1.7, r * 1.4);
  ctx.beginPath();
  for (let i = 1; i < 3; i++) {
    ctx.moveTo(x - r * 0.85 + (i * r * 1.7) / 3, y - r * 0.7);
    ctx.lineTo(x - r * 0.85 + (i * r * 1.7) / 3, y + r * 0.7);
  }
  ctx.moveTo(x - r * 0.85, y);
  ctx.lineTo(x + r * 0.85, y);
  ctx.stroke();
  ctx.restore();
}

export default {
  id: 's06',
  num: '06',
  file: '06-teacher',
  title: '专家规则 + 对局数据',
  duration: 18,
  draw(ctx, t) {
    chapter(ctx, t, { num: '06', title: '专家规则 + 对局数据', sub: '先拼出一个复杂但更强的"老师"：能用的知识全都装进去' });

    // ---- rules panel
    const ra = p(t, 2.0, 0.6);
    panel(ctx, RP.x, RP.y + (1 - ra) * 20, RP.w, RP.h, { alpha: ra, accent: C.gold });
    ctx.save();
    ctx.globalAlpha *= ra;
    I.book(ctx, RP.x + 46, RP.y + 46, 36, C.gold);
    text(ctx, '专家规则', RP.x + 80, RP.y + 56, { size: 28, weight: 700 });
    text(ctx, '整理自公开攻略与高手对局', RP.x + RP.w - 28, RP.y + 56, { size: 18, color: C.sub, align: 'right' });
    ctx.restore();
    RULES.forEach(([cond, act], i) => {
      const k = p(t, 2.6 + i * 0.45, 0.6);
      const y = RP.y + 122 + i * 56;
      const x = RP.x + 34 + (1 - k) * -24;
      ctx.save();
      ctx.globalAlpha *= k;
      rr(ctx, x, y - 30, RP.w - 68, 44, 10);
      ctx.fillStyle = 'rgba(255,255,255,0.035)';
      ctx.fill();
      text(ctx, '如果', x + 16, y, { size: 18, color: C.dim });
      text(ctx, cond, x + 62, y, { size: 21, weight: 600 });
      text(ctx, '→', x + 330, y, { size: 22, color: C.gold });
      text(ctx, act, x + 364, y, { size: 21, weight: 700, color: C.gold });
      ctx.restore();
    });

    // ---- data panel
    const da = p(t, 3.2, 0.6);
    panel(ctx, DP.x, DP.y + (1 - da) * 20, DP.w, DP.h, { alpha: da, accent: C.green });
    ctx.save();
    ctx.globalAlpha *= da;
    I.database(ctx, DP.x + 46, DP.y + 44, 34, C.green);
    text(ctx, '对局数据', DP.x + 80, DP.y + 54, { size: 28, weight: 700 });
    text(ctx, '把牌放进真实牌组，在关口重打很多遍', DP.x + DP.w - 28, DP.y + 54, { size: 18, color: C.sub, align: 'right' });
    // scrolling log
    const lx = DP.x + 26, ly = DP.y + 84, lw = 276, lh = 196;
    ctx.save();
    rr(ctx, lx, ly, lw, lh, 10);
    ctx.fillStyle = 'rgba(0,0,0,0.25)';
    ctx.fill();
    ctx.clip();
    const scroll = Math.max(0, t - 3.6) * 46;
    LOG.forEach((g, i) => {
      const y = ly + 26 + i * 26 - (scroll % (LOG.length * 26));
      const yy = y < ly - 20 ? y + LOG.length * 26 : y;
      if (yy > ly + lh + 20) return;
      text(ctx, `#${g.seed}`, lx + 12, yy, { size: 14, fam: 'mono', color: C.dim });
      text(ctx, `${g.where}`, lx + 130, yy, { size: 14, color: C.sub });
      text(ctx, g.win ? `胜 ${g.hp} 血` : '败', lx + lw - 14, yy, { size: 14, weight: 700, color: g.win ? C.green : C.red, align: 'right' });
    });
    const fade = ctx.createLinearGradient(0, ly, 0, ly + lh);
    fade.addColorStop(0, 'rgba(14,13,26,1)');
    fade.addColorStop(0.2, 'rgba(14,13,26,0)');
    fade.addColorStop(0.8, 'rgba(14,13,26,0)');
    fade.addColorStop(1, 'rgba(14,13,26,1)');
    ctx.fillStyle = fade;
    ctx.fillRect(lx, ly, lw, lh);
    ctx.restore();
    // value table
    const tx = DP.x + 396, ty = DP.y + 110, cw = 57, ch = 38;
    TABLE_COLS.forEach((c, j) => text(ctx, c, tx + j * cw + cw / 2, ty - 10, { size: 12, color: C.sub, align: 'center' }));
    TABLE_ROWS.forEach((r, i) => {
      text(ctx, r, tx - 10, ty + i * ch + 25, { size: 15, color: C.ink, align: 'right' });
      TABLE_COLS.forEach((c, j) => {
        const v = hash(i, j, 7) * 2 - 0.7;
        const k = p(t, 4.4 + (i * 4 + j) * 0.12, 0.4);
        rr(ctx, tx + j * cw + 3, ty + i * ch + 3, cw - 6, ch - 6, 6);
        ctx.fillStyle = 'rgba(255,255,255,0.04)';
        ctx.fill();
        if (k > 0) {
          rr(ctx, tx + j * cw + 3, ty + i * ch + 3, cw - 6, ch - 6, 6);
          ctx.fillStyle = rgba(v > 0 ? C.green : C.red, (0.18 + 0.5 * Math.min(1, Math.abs(v))) * k);
          ctx.fill();
          text(ctx, v > 0 ? '↑' : '↓', tx + j * cw + cw / 2, ty + i * ch + 26, { size: 16, weight: 700, align: 'center', color: v > 0 ? C.green : C.red, alpha: k });
        }
      });
    });
    ctx.restore();

    // ---- modules around the crest
    MODS.forEach((m) => {
      const k = p(t, m.t, 0.6, ease.outBack);
      if (k <= 0) return;
      const x = m.x - MW / 2, y = m.y - MH / 2;
      // feed from panels
      if (m.key === 'rules') flow(ctx, sCurve(RP.x + RP.w + 6, RP.y + 150, x - 8, m.y, 0.5), p(t, m.t - 0.6, 0.7), t, { color: C.gold, dots: 3, speed: 0.7 });
      if (m.key === 'table') flow(ctx, sCurve(DP.x + DP.w + 6, DP.y + 150, x - 8, m.y, 0.5), p(t, m.t - 0.6, 0.7), t, { color: C.green, dots: 3, speed: 0.7 });
      // spoke to crest
      const sk = p(t, 10.0, 0.8);
      const P = [{ x: m.x, y: m.y }, { x: m.x, y: lerp(m.y, CREST.y, 0.5) }, { x: lerp(m.x, CREST.x, 0.5), y: CREST.y }, { x: CREST.x + (m.x < CREST.x ? -70 : 70), y: CREST.y + (m.y < CREST.y ? -40 : 40) }];
      flow(ctx, P, sk, t, { color: m.color, dots: 2, speed: 0.9, alpha: 0.9 });
      ctx.save();
      ctx.translate(m.x, m.y);
      ctx.scale(clamp(k, 0, 1.2), clamp(k, 0, 1.2));
      ctx.translate(-m.x, -m.y);
      panel(ctx, x, y, MW, MH, { r: 16, stroke: rgba(m.color, 0.45), glow: m.color, glowA: 0.08 });
      m.icon(ctx, x + 44, m.y - 2, 38, m.color);
      text(ctx, m.title, x + 84, m.y - 8, { size: 24, weight: 700, color: m.color });
      text(ctx, m.desc, x + 84, m.y + 24, { size: 16, color: C.sub });
      ctx.restore();
    });

    teacherCrest(ctx, CREST.x, CREST.y, 96, p(t, 10.4, 0.9), t);

    // ---- verdict
    const vk = p(t, 12.0, 0.7);
    const msg = '复杂但更强：网络打分之外，还要查表、套规则';
    const mw = measure(ctx, msg, 24, 500);
    ctx.save();
    ctx.globalAlpha *= vk;
    I.crown(ctx, CREST.x - mw / 2 - 12, 906, 30, C.gold);
    ctx.restore();
    text(ctx, msg, CREST.x + 14, 917, { size: 24, weight: 500, color: C.sub, alpha: vk, align: 'center' });
  },
};
