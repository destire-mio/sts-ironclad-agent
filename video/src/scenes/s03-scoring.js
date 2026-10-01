// 03 给选项打分: the current state becomes a vector; each candidate is paired
// with it and passed through the same network; the highest score wins.
import { C, p, ease, clamp, rgba, text, glow, panel, chapter, flow, sCurve, hash, TAU, ring, chip, rr } from '../engine.js';
import * as I from '../icons.js';
import { card, CARDS, netLayout, network, scoreBar, hpBar, vector } from '../widgets.js';

const SP = { x: 110, y: 262, w: 420, h: 610 };
const VX = 612, VY = 330, VCELL = 19, VN = 20;
const ROWS = [330, 478, 626, 774];
const CANDS = [
  { spec: CARDS.shrug, score: 0.58 },
  { spec: CARDS.heavy, score: 0.41 },
  { spec: CARDS.inflame, score: 0.73 },
  { spec: null, label: '跳过', score: 0.22 },
];
const BEST = 2;
const CARD_X = 770;
const PAIR_X = 868;
const NET = netLayout(1170, 400, 240, 320, [6, 8, 8, 1]);
const NET_IN = { x: 1170, y: 560 };
const NET_OUT = { x: 1410, y: 560 };
const SX = 1490;
const T_ROW = (j) => 7.0 + j * 0.95;

function stateRows(ctx, t) {
  const rows = [
    ['楼层', '第 23 层 · 第二幕', I.star, C.gold],
    ['生命', null, I.heart, C.red],
    ['金币', '143', I.coin, C.gold],
    ['牌组', '22 张', I.doc, C.ink],
    ['遗物', null, I.chest, C.violet],
    ['钥匙', '1 / 3', I.key, C.gold],
    ['路线', '前方：精英 · 篝火', I.swords, C.ink],
  ];
  rows.forEach(([label, value, icon, col], i) => {
    const y = SP.y + 122 + i * 68;
    const a = p(t, 2.3 + i * 0.12, 0.5);
    const pulse = t > 4.2 && t < 6.2 ? Math.max(0, Math.sin((t - 4.2 - i * 0.08) * 6)) : 0;
    ctx.save();
    ctx.globalAlpha *= a;
    if (pulse > 0) glow(ctx, SP.x + 40, y - 8, 30, C.cyan, 0.4 * pulse);
    if (icon === I.heart) I.heart(ctx, SP.x + 40, y - 8, 26, C.red);
    else icon(ctx, SP.x + 40, y - 8, 26, col);
    text(ctx, label, SP.x + 72, y, { size: 22, color: C.sub });
    if (label === '生命') hpBar(ctx, SP.x + 150, y - 20, 220, 54, 80, { h: 20 });
    else if (label === '遗物') {
      const cols = [C.red, C.gold, C.cyan, C.violet, C.green];
      cols.forEach((cc, j) => {
        ctx.beginPath();
        ctx.arc(SP.x + 166 + j * 40, y - 8, 14, 0, TAU);
        ctx.fillStyle = rgba(cc, 0.25);
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = cc;
        ctx.stroke();
      });
    } else text(ctx, value, SP.x + 150, y, { size: 23, weight: 700, color: C.ink });
    ctx.restore();
  });
}

export default {
  id: 's03',
  num: '03',
  file: '03-scoring',
  title: '给每个选项打分',
  duration: 18,
  draw(ctx, t) {
    chapter(ctx, t, { num: '03', title: '给每个选项打分', sub: '看懂当前局面，给每个候选打一个分，选分最高的' });

    // ---- state panel
    const pa = p(t, 2.0, 0.7);
    panel(ctx, SP.x, SP.y + (1 - pa) * 24, SP.w, SP.h, { alpha: pa, accent: C.cyan });
    text(ctx, '当前局面', SP.x + 32, SP.y + 58, { size: 28, weight: 700, alpha: pa });
    text(ctx, '只用公开信息', SP.x + SP.w - 32, SP.y + 58, { size: 18, color: C.cyan, align: 'right', alpha: pa });
    stateRows(ctx, t);

    // ---- encode into a vector
    const ek = p(t, 4.2, 1.4, ease.inOutCubic);
    for (let i = 0; i < 7; i++) {
      const y0 = SP.y + 112 + i * 66;
      const P = sCurve(SP.x + SP.w - 10, y0, VX - 16, VY + 30 + i * 52, 0.5);
      flow(ctx, P, ek, t, { color: C.cyan, alpha: 0.9 * (1 - p(t, 6.4, 0.6)), dots: 2, speed: 1.1, width: 1.5 });
    }
    const vk = p(t, 4.9, 1.0);
    const vh = vector(ctx, VX, VY, VCELL, VN, vk, { color: C.cyan, seed: 7 });
    text(ctx, '局面 → 一串数字', VX, VY + vh + 40, { size: 20, color: C.cyan, align: 'center', alpha: vk });

    // ---- copy lines from the state vector to every pair (drawn under the cards)
    CANDS.forEach((cd, j) => {
      const cp = p(t, 6.1 + j * 0.15, 0.6);
      flow(ctx, sCurve(VX + 14, VY + 8 + j * 110, PAIR_X - 6, ROWS[j], 0.5), cp, t, { color: C.cyan, alpha: 0.5 * (1 - p(t, 7.0 + j * 0.95, 0.4)), dots: 0, width: 1.2 });
    });

    // ---- candidates
    CANDS.forEach((cd, j) => {
      const y = ROWS[j];
      const a = p(t, 5.6 + j * 0.18, 0.6, ease.outBack);
      const decided = p(t, 11.0, 0.6);
      const isBest = j === BEST;
      const dim = decided * (isBest ? 0 : 0.7);
      ctx.save();
      ctx.globalAlpha *= clamp(a);
      if (cd.spec) {
        card(ctx, CARD_X, y + (isBest ? -6 * decided : 0), cd.spec, { scale: 0.6 * (isBest ? 1 + 0.08 * decided : 1), glow: isBest ? decided : 0, outline: isBest ? decided : 0, dim });
      } else {
        rr(ctx, CARD_X - 45, y - 62, 90, 124, 10);
        ctx.setLineDash([6, 6]);
        ctx.strokeStyle = rgba(C.sub, 0.6 * (1 - dim));
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.setLineDash([]);
        text(ctx, '跳过', CARD_X, y + 8, { size: 22, weight: 700, color: C.sub, align: 'center', alpha: 1 - dim });
      }
      ctx.restore();

      // pair = state vector + candidate features
      const pk = p(t, 6.2 + j * 0.15, 0.7);
      const n1 = 9, n2 = 6, cw = 12;
      for (let i = 0; i < n1 + n2; i++) {
        const ki = clamp(pk * 1.6 - i / (n1 + n2) * 0.6);
        if (ki <= 0) continue;
        const col = i < n1 ? C.cyan : C.gold;
        const v = hash(j * 31 + (i < n1 ? 0 : 99), i);
        rr(ctx, PAIR_X + i * (cw + 3), y - cw / 2, cw, cw, 3);
        ctx.fillStyle = rgba(col, (0.2 + 0.7 * v) * ki * (1 - dim * 0.7));
        ctx.fill();
      }

      // into the network and out to the score
      const tr = T_ROW(j);
      const kin = p(t, tr, 0.35, ease.inOutQuad);
      const pairEnd = PAIR_X + (n1 + n2) * (cw + 3) + 8;
      const active = t >= tr && t < tr + 0.95;
      flow(ctx, sCurve(pairEnd, y, NET_IN.x - 14, NET_IN.y, 0.55), kin, t, { color: active ? C.gold : C.cyan, alpha: active ? 1 : 0.35 * kin, dots: active ? 3 : 0, speed: 2.2, width: active ? 2.4 : 1.4 });
      const kout = p(t, tr + 0.55, 0.3, ease.inOutQuad);
      flow(ctx, sCurve(NET_OUT.x + 14, NET_OUT.y, SX - 16, y, 0.55), kout, t, { color: active ? C.gold : C.cyan, alpha: active ? 1 : 0.3 * kout, dots: active ? 3 : 0, speed: 2.2, width: active ? 2.4 : 1.4 });

      // score
      const sk = p(t, tr + 0.75, 0.6);
      const win = isBest && decided > 0;
      const col = win ? C.gold : C.cyan;
      scoreBar(ctx, SX, y, 160, cd.score, sk, { color: col, h: 12, alpha: p(t, 6.6 + j * 0.15, 0.5) * (1 - dim * 0.6) });
      text(ctx, (cd.score * sk).toFixed(2), SX + 272, y + 12, { size: 34, weight: 700, fam: 'mono', color: win ? C.gold : C.ink, align: 'right', alpha: clamp(sk * 3) * (1 - dim * 0.6) });
      if (win) {
        I.check(ctx, SX + 300, y + 0, 30, C.gold);
        ring(ctx, CARD_X, y, clamp((t - 11.0) / 0.9), { r0: 50, r1: 150, color: C.gold });
      }
    });

    // ---- network
    let act = -1;
    for (let j = 0; j < 4; j++) {
      const tr = T_ROW(j);
      if (t >= tr + 0.2 && t < tr + 0.8) act = (t - tr - 0.2) / 0.6;
    }
    const nk = p(t, 5.8, 1.0);
    network(ctx, NET, { k: nk, t, color: C.cyan, pulse: act >= 0 ? 1 : 0.3, act });
    text(ctx, '同一个网络', 1290, 372, { size: 24, weight: 700, align: 'center', alpha: nk });
    text(ctx, '11195 维输入 → 384 → 1 个分数', 1290, 768, { size: 18, fam: 'sans', color: C.sub, align: 'center', alpha: nk });
    text(ctx, '分数', SX + 136, 268, { size: 22, weight: 700, color: C.sub, align: 'center', alpha: p(t, 7.0, 0.5) });
    text(ctx, '数值为示意', SX + 300, 268, { size: 15, color: C.dim, align: 'right', alpha: p(t, 7.0, 0.5) });

    // ---- verdict + generalisation
    const vk2 = p(t, 11.4, 0.6);
    chip(ctx, CARD_X - 70, 878, '选分最高的：拿「燃烧」', { color: C.gold, size: 24, alpha: vk2, weight: 700, icon: I.check });
    const kinds = [['选路', I.swords], ['选牌', I.doc], ['商店', I.bag], ['篝火', I.campfire], ['事件', I.question], ['遗物', I.chest], ['钥匙', I.key]];
    const gk = p(t, 13.0, 0.6);
    text(ctx, '所有局外选择，都用同一种打分方式：', 1190, 868, { size: 22, color: C.sub, alpha: gk });
    kinds.forEach(([label], i) => {
      const k = p(t, 13.4 + i * 0.16, 0.5, ease.outBack);
      chip(ctx, 1190 + i * 88, 916, label, { color: C.cyan, size: 18, alpha: clamp(k), padX: 12 });
    });
  },
};
