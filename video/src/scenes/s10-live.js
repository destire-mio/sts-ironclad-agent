// 10 真实游戏与决策执行的闭环: the original game sends its state through a mod;
// the AI routes it to search (combat) or the frozen network (everything else)
// and sends one command back, which the game executes.
import { C, p, ease, clamp, lerp, rgba, text, glow, panel, chapter, hash, chip, rr, sCurve, flow, measure } from '../engine.js';
import * as I from '../icons.js';
import { card, CARDS, ironclad, monster, hpBar } from '../widgets.js';

const GW = { x: 110, y: 262, w: 660, h: 560 };
const SA = { x: GW.x + 20, y: GW.y + 64, w: GW.w - 40, h: 380 };
const AB = { x: 1150, y: 262, w: 660, h: 600 };
const LANE_IN = 392, LANE_OUT = 712;
const C0 = 2.8, CD = 3.6;
const CYCLES = [
  { screen: 'map', floor: 22, combat: false, state: '{"screen":"MAP","floor":22,…}', cmd: 'choose 1' },
  { screen: 'combat', floor: 23, combat: true, state: '{"screen":"COMBAT","rng":{…},…}', cmd: 'play 1 0' },
  { screen: 'reward', floor: 23, combat: false, state: '{"screen":"CARD_REWARD",…}', cmd: 'choose 2' },
  { screen: 'rest', floor: 24, combat: false, state: '{"screen":"REST","hp":41,…}', cmd: 'choose 0' },
];
const ROUTER = { x: AB.x + 330, y: AB.y + 150 };
const BOX_S = { x: AB.x + 36, y: AB.y + 250, w: 280, h: 170 };
const BOX_N = { x: AB.x + 344, y: AB.y + 250, w: 280, h: 170 };
const OUTC = { x: AB.x + 330, y: AB.y + 500 };

function cycleAt(t) {
  const k = (t - C0) / CD;
  const i = Math.floor(k);
  if (i < 0) return null;
  if (i >= CYCLES.length) return { i: CYCLES.length - 1, u: CD, done: true };
  return { i, u: (k - i) * CD };
}

function drawScreen(ctx, kind, u, alpha, t) {
  if (alpha <= 0) return;
  const cx = SA.x + SA.w / 2, cy = SA.y + SA.h / 2;
  const act = clamp((u - 3.0) / 0.6); // executing the command
  ctx.save();
  ctx.globalAlpha *= alpha;
  ctx.beginPath();
  ctx.roundRect(SA.x, SA.y, SA.w, SA.h, 12);
  ctx.clip();
  const bg = ctx.createLinearGradient(0, SA.y, 0, SA.y + SA.h);
  bg.addColorStop(0, '#1c1830');
  bg.addColorStop(1, '#0e0c18');
  ctx.fillStyle = bg;
  ctx.fillRect(SA.x, SA.y, SA.w, SA.h);
  if (kind === 'map') {
    const nodes = [[cx - 150, cy + 120, 'fight'], [cx, cy + 120, 'event'], [cx + 150, cy + 120, 'shop'], [cx - 90, cy, 'elite'], [cx + 90, cy, 'rest'], [cx, cy - 120, 'fight']];
    ctx.strokeStyle = 'rgba(255,255,255,0.18)';
    ctx.setLineDash([3, 6]);
    ctx.lineWidth = 2;
    [[0, 3], [1, 3], [1, 4], [2, 4], [3, 5], [4, 5]].forEach(([a, b]) => {
      ctx.beginPath();
      ctx.moveTo(nodes[a][0], nodes[a][1]);
      ctx.lineTo(nodes[b][0], nodes[b][1]);
      ctx.stroke();
    });
    ctx.setLineDash([]);
    nodes.forEach(([x, y, k], i) => I.mapNode(ctx, x, y, 24, k, { active: i === 1 ? 0.6 : i === 4 && act > 0 ? act : 0 }));
    // token moves from event (1) to rest (4)
    const tx = lerp(nodes[1][0], nodes[4][0], ease.inOutCubic(act)), ty = lerp(nodes[1][1], nodes[4][1], ease.inOutCubic(act));
    glow(ctx, tx, ty - 34, 22, C.gold, 0.8);
    I.star(ctx, tx, ty - 34, 18, C.gold);
    text(ctx, '地图', SA.x + 16, SA.y + 30, { size: 18, color: C.sub });
  } else if (kind === 'combat') {
    ironclad(ctx, cx - 160, cy - 40, 100);
    const hit = act > 0.5 ? Math.exp(-(act - 0.5) * 8) : 0;
    monster(ctx, cx + 150 + Math.sin(t * 60) * 6 * hit, cy - 40, 130, { t, color: '#8a4a9e' });
    hpBar(ctx, cx + 85, cy + 40, 130, act > 0.5 ? 26 : 34, 46, { h: 14 });
    hpBar(ctx, cx - 225, cy + 40, 130, 41, 80, { h: 14 });
    [CARDS.strike, CARDS.bash, CARDS.defend, CARDS.shrug].forEach((cd, j) => {
      let x = cx - 150 + j * 100, y = cy + 140, sc = 0.48, a = 1;
      if (j === 1 && act > 0) {
        x = lerp(x, cx + 150, ease.inCubic(act));
        y = lerp(y, cy - 40, ease.inCubic(act));
        sc = lerp(0.48, 0.25, act);
        a = 1 - clamp((act - 0.7) / 0.3);
      }
      card(ctx, x, y, cd, { scale: sc, rot: (j - 1.5) * 0.05, alpha: a });
    });
    if (act > 0.5) text(ctx, '-8', cx + 200, cy - 90 - act * 20, { size: 34, weight: 900, fam: 'mono', color: '#ffd166', stroke: '#3a0a0a', strokeWidth: 5 });
    text(ctx, '战斗', SA.x + 16, SA.y + 30, { size: 18, color: C.sub });
  } else if (kind === 'reward') {
    [CARDS.pommel, CARDS.metal, CARDS.inflame].forEach((cd, j) => {
      const chosen = j === 2;
      card(ctx, cx - 160 + j * 160, cy + 10 - (chosen ? 30 * ease.outBack(act) : 0), cd, { scale: 0.75, glow: chosen ? act : 0, outline: chosen ? act : 0, dim: !chosen ? act * 0.6 : 0 });
    });
    text(ctx, '选一张牌加入牌组', SA.x + 16, SA.y + 30, { size: 18, color: C.sub });
  } else if (kind === 'rest') {
    I.campfire(ctx, cx, cy - 30, 120, C.orange);
    glow(ctx, cx, cy - 30, 160, C.orange, 0.3 + 0.1 * Math.sin(t * 8));
    ['休息', '锻造'].forEach((s, j) => {
      const chosen = j === 0;
      const x = cx - 110 + j * 220, y = cy + 120;
      rr(ctx, x - 80, y - 28, 160, 56, 14);
      ctx.fillStyle = chosen && act > 0 ? rgba(C.green, 0.25 * act) : 'rgba(255,255,255,0.06)';
      ctx.fill();
      ctx.strokeStyle = chosen && act > 0 ? C.green : 'rgba(255,255,255,0.25)';
      ctx.lineWidth = 2;
      ctx.stroke();
      text(ctx, s, x, y + 8, { size: 22, weight: 700, align: 'center' });
    });
    if (act > 0) text(ctx, '+24', cx + 70, cy - 60 - act * 20, { size: 30, weight: 900, fam: 'mono', color: C.green, alpha: act });
    text(ctx, '篝火', SA.x + 16, SA.y + 30, { size: 18, color: C.sub });
  }
  ctx.restore();
}

function packet(ctx, x, y, label, col, a) {
  const w = measure(ctx, label, 16, 600, 'mono') + 28;
  ctx.save();
  ctx.globalAlpha *= a;
  glow(ctx, x, y, w * 0.7, col, 0.35, 1, 0.4);
  rr(ctx, x - w / 2, y - 19, w, 38, 10);
  ctx.fillStyle = rgba('#141226', 0.96);
  ctx.fill();
  ctx.strokeStyle = col;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.restore();
  text(ctx, label, x, y + 6, { size: 16, weight: 600, fam: 'mono', align: 'center', color: C.ink, alpha: a });
}

function box(ctx, b, title, sub, col, on, icon) {
  panel(ctx, b.x, b.y, b.w, b.h, { r: 16, stroke: rgba(col, 0.25 + 0.65 * on), glow: col, glowA: 0.05 + 0.2 * on, alpha: 0.55 + 0.45 * Math.max(on, 0.3) });
  ctx.save();
  ctx.globalAlpha *= 0.55 + 0.45 * Math.max(on, 0.3);
  icon(ctx, b.x + 44, b.y + 52, 40, col);
  text(ctx, title, b.x + 80, b.y + 60, { size: 25, weight: 700, color: col });
  text(ctx, sub, b.x + 26, b.y + 112, { size: 17, color: C.sub });
  ctx.restore();
}

export default {
  id: 's10',
  num: '10',
  file: '10-live',
  title: '接入真实游戏：闭环运行',
  duration: 20.5,
  draw(ctx, t) {
    chapter(ctx, t, { num: '10', title: '接入真实游戏：闭环运行', sub: '原版游戏把状态发出来，AI 回一条指令，游戏执行，再发下一份状态' });

    const cyc = cycleAt(t);
    const i = cyc ? cyc.i : 0;
    const u = cyc ? cyc.u : 0;
    const cur = CYCLES[i];

    // ---- game window
    const ga = p(t, 2.0, 0.6);
    panel(ctx, GW.x, GW.y, GW.w, GW.h, { alpha: ga, accent: C.gold });
    text(ctx, '杀戮尖塔 · 原版游戏', GW.x + 24, GW.y + 44, { size: 22, weight: 700, alpha: ga });
    text(ctx, 'Java · A20 铁甲战士', GW.x + GW.w - 24, GW.y + 44, { size: 17, color: C.sub, align: 'right', alpha: ga });
    // screens crossfade
    if (cyc && !cyc.done) {
      const prev = i > 0 ? CYCLES[i - 1] : null;
      const fade = clamp(u / 0.3);
      if (prev && fade < 1) drawScreen(ctx, prev.screen, CD, ga * (1 - fade), t);
      drawScreen(ctx, cur.screen, u, ga * fade, t);
    } else if (cyc && cyc.done) {
      drawScreen(ctx, cur.screen, CD, ga, t);
    } else {
      drawScreen(ctx, CYCLES[0].screen, 0, ga * p(t, 2.2, 0.5), t);
    }
    // floor progress
    const floor = cyc ? cur.floor : 22;
    const fy = GW.y + GW.h - 54;
    ctx.save();
    ctx.globalAlpha *= ga;
    text(ctx, `第 ${floor} 层`, GW.x + 24, fy + 8, { size: 22, weight: 700, color: C.gold, fam: 'sans' });
    rr(ctx, GW.x + 130, fy - 4, 440, 10, 5);
    ctx.fillStyle = 'rgba(255,255,255,0.08)';
    ctx.fill();
    rr(ctx, GW.x + 130, fy - 4, 440 * (floor / 56), 10, 5);
    ctx.fillStyle = C.gold;
    ctx.fill();
    I.heart(ctx, GW.x + 600, fy + 1, 30, '#d8283a');
    ctx.restore();

    // ---- pipe and mod
    const pa = p(t, 2.3, 0.6);
    const inP = sCurve(GW.x + GW.w + 4, LANE_IN, AB.x - 4, LANE_IN, 0.5);
    const outP = sCurve(AB.x - 4, LANE_OUT, GW.x + GW.w + 4, LANE_OUT, 0.5);
    flow(ctx, inP, pa, t, { color: C.violet, dots: 0, width: 3, arrow: true });
    flow(ctx, outP, pa, t, { color: C.gold, dots: 0, width: 3, arrow: true });
    text(ctx, '状态', 960, LANE_IN - 34, { size: 19, weight: 700, color: C.violet, align: 'center', alpha: pa });
    text(ctx, '指令', 960, LANE_OUT + 50, { size: 19, weight: 700, color: C.gold, align: 'center', alpha: pa });
    chip(ctx, 960, (LANE_IN + LANE_OUT) / 2 - 14, 'CommunicationMod', { color: C.ink, size: 20, align: 'center', fam: 'mono', alpha: pa, weight: 600 });
    text(ctx, '游戏 Mod：转发状态和指令', 960, (LANE_IN + LANE_OUT) / 2 + 36, { size: 16, color: C.sub, align: 'center', alpha: pa });

    // ---- AI box
    const aa = p(t, 2.2, 0.6);
    panel(ctx, AB.x, AB.y, AB.w, AB.h, { alpha: aa, accent: C.cyan });
    text(ctx, 'AI 决策进程', AB.x + 24, AB.y + 44, { size: 22, weight: 700, alpha: aa });
    const decide = cyc && !cyc.done ? clamp((u - 1.1) / 0.4) : 0;
    const working = cyc && !cyc.done && u > 1.3 && u < 2.4;
    // router diamond
    ctx.save();
    ctx.globalAlpha *= aa;
    ctx.translate(ROUTER.x, ROUTER.y);
    const rOn = cyc && !cyc.done && u > 0.9 && u < 1.6 ? 1 : 0;
    if (rOn) glow(ctx, 0, 0, 90, C.ink, 0.25);
    ctx.beginPath();
    ctx.moveTo(0, -46); ctx.lineTo(96, 0); ctx.lineTo(0, 46); ctx.lineTo(-96, 0);
    ctx.closePath();
    ctx.fillStyle = '#1b1a30';
    ctx.fill();
    ctx.strokeStyle = rgba(C.ink, 0.4 + 0.5 * rOn);
    ctx.lineWidth = 2;
    ctx.stroke();
    text(ctx, '在战斗中？', 0, 7, { size: 20, weight: 700, align: 'center' });
    ctx.restore();
    // router input from the left port
    flow(ctx, sCurve(AB.x + 4, LANE_IN, ROUTER.x - 98, ROUTER.y, 0.5), aa, t, { color: C.violet, dots: 0, width: 2 });
    const isC = cur.combat;
    const sOn = cyc && !cyc.done && isC ? decide : 0;
    const nOn = cyc && !cyc.done && !isC ? decide : 0;
    const toS = [{ x: ROUTER.x - 40, y: ROUTER.y + 30 }, { x: ROUTER.x - 80, y: ROUTER.y + 70 }, { x: BOX_S.x + BOX_S.w / 2, y: BOX_S.y - 40 }, { x: BOX_S.x + BOX_S.w / 2, y: BOX_S.y - 4 }];
    const toN = [{ x: ROUTER.x + 40, y: ROUTER.y + 30 }, { x: ROUTER.x + 80, y: ROUTER.y + 70 }, { x: BOX_N.x + BOX_N.w / 2, y: BOX_N.y - 40 }, { x: BOX_N.x + BOX_N.w / 2, y: BOX_N.y - 4 }];
    flow(ctx, toS, aa, t, { color: C.red, dots: sOn > 0 ? 2 : 0, speed: 1.5, width: sOn > 0 ? 3 : 1.5, alpha: 0.5 + 0.5 * sOn });
    flow(ctx, toN, aa, t, { color: C.cyan, dots: nOn > 0 ? 2 : 0, speed: 1.5, width: nOn > 0 ? 3 : 1.5, alpha: 0.5 + 0.5 * nOn });
    text(ctx, '是', ROUTER.x - 104, ROUTER.y + 70, { size: 18, weight: 700, color: C.red, alpha: aa });
    text(ctx, '否', ROUTER.x + 92, ROUTER.y + 70, { size: 18, weight: 700, color: C.cyan, alpha: aa });
    ctx.save();
    ctx.globalAlpha *= aa;
    box(ctx, BOX_S, '模拟器搜索', '导入状态和随机数，试打出牌', C.red, sOn, I.tree);
    box(ctx, BOX_N, '冻结网络', '给每个选项打分，选最高', C.cyan, nOn, I.brain);
    ctx.restore();
    if (working) {
      const b = isC ? BOX_S : BOX_N;
      const col = isC ? C.red : C.cyan;
      const k = clamp((u - 1.3) / 1.0);
      for (let j = 0; j < 5; j++) {
        const v = isC ? 0.3 + 0.6 * hash(i, j) : 0.25 + 0.65 * hash(i + 7, j);
        rr(ctx, b.x + 26 + j * 48, b.y + 140 - 18 * v * k, 34, 18 * v * k + 4, 3);
        ctx.fillStyle = rgba(col, 0.4 + 0.5 * v);
        ctx.fill();
      }
    }
    // output command
    const oc = cyc && !cyc.done ? clamp((u - 2.0) / 0.3) * (1 - clamp((u - 2.9) / 0.3)) : 0;
    const outFrom = isC ? BOX_S : BOX_N;
    flow(ctx, [{ x: outFrom.x + outFrom.w / 2, y: outFrom.y + outFrom.h + 4 }, { x: outFrom.x + outFrom.w / 2, y: OUTC.y - 20 }, { x: OUTC.x, y: OUTC.y - 40 }, { x: OUTC.x, y: OUTC.y - 22 }], oc, t, { color: C.gold, dots: 0, width: 2, alpha: oc });
    text(ctx, '回复一条指令', OUTC.x, OUTC.y + 52, { size: 16, color: C.sub, align: 'center', alpha: aa });
    if (oc > 0) packet(ctx, OUTC.x, OUTC.y, cur.cmd, C.gold, oc);
    flow(ctx, sCurve(OUTC.x - 70, OUTC.y + 30, AB.x + 4, LANE_OUT, 0.5), aa, t, { color: C.gold, dots: 0, width: 2 });

    // ---- moving packets
    if (cyc && !cyc.done) {
      const kin = clamp((u - 0.3) / 0.8);
      if (kin > 0 && kin < 1) {
        const q = inP[0], q3 = inP[3];
        const x = lerp(q.x - 40, q3.x + 40, ease.inOutCubic(kin));
        packet(ctx, x, LANE_IN, cur.state, C.violet, Math.sin(kin * Math.PI) * 1.4 > 1 ? 1 : Math.sin(kin * Math.PI) * 1.4);
      }
      const kout = clamp((u - 2.4) / 0.6);
      if (kout > 0 && kout < 1) {
        const x = lerp(AB.x + 40, GW.x + GW.w - 40, ease.inOutCubic(kout));
        packet(ctx, x, LANE_OUT, cur.cmd, C.gold, Math.min(1, Math.sin(kout * Math.PI) * 1.4));
      }
      // game export flash
      if (u < 0.5) glow(ctx, GW.x + GW.w, LANE_IN, 60, C.violet, (1 - u / 0.5) * 0.8);
    }

    // ---- caption
    const ck = p(t, C0 + CYCLES.length * CD - 0.2, 0.7);
    text(ctx, '从涅奥一路到心脏，每一步都是：读状态 → 做决定 → 执行', 960, 930, { size: 28, weight: 500, color: C.sub, align: 'center', alpha: ck });
  },
};
