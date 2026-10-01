// 02 分工: a cursor walks the run's map; non-combat rooms light up the network
// panel, combat rooms light up the search panel.
import { C, p, ease, clamp, lerp, rgba, text, glow, panel, chapter, flow, vCurve, hash, TAU, mix } from '../engine.js';
import * as I from '../icons.js';
import { card, CARDS, netLayout, network, scoreBar, ironclad, monster } from '../widgets.js';

const ROUTE = ['start', 'fight', 'event', 'fight', 'shop', 'elite', 'rest', 'chest', 'boss'];
const X0 = 240, X1 = 1680, RY = 318;
const nodeX = (i) => lerp(X0, X1, i / (ROUTE.length - 1));
const COMBAT = new Set(['fight', 'elite', 'boss']);

const CHOICES = {
  start: [['移除一张牌', 0.71], ['获得 100 金币', 0.52], ['最大生命 +8', 0.44]],
  event: [['用生命换遗物', 0.38], ['离开', 0.62]],
  shop: [['买「耸肩无视」', 0.66], ['删除一张「打击」', 0.74], ['离开', 0.31]],
  rest: [['休息：回复生命', 0.69], ['升级「痛击」', 0.47]],
  chest: [['拿遗物', 0.42], ['拿蓝钥匙', 0.64]],
};

const LP = { x: 120, y: 448, w: 820, h: 452 };
const RP = { x: 980, y: 448, w: 820, h: 452 };
const NET = netLayout(LP.x + 70, LP.y + 140, 280, 230, [5, 7, 7, 1]);

// Small deterministic search tree for the combat panel.
const TREE = (() => {
  const nodes = [{ x: 0, y: 0, d: 0, parent: -1, order: 0 }];
  let order = 1;
  const grow = (pi, d) => {
    if (d >= 3) return;
    const n = d === 0 ? 3 : 3 - (hash(pi, d) > 0.5 ? 1 : 0);
    for (let i = 0; i < n; i++) {
      const id = nodes.length;
      nodes.push({ d: d + 1, parent: pi, i, n, order: order++ });
      grow(id, d + 1);
    }
  };
  grow(0, 0);
  // layout: leaves spread evenly
  const leaves = [];
  const kids = nodes.map(() => []);
  nodes.forEach((nd, id) => nd.parent >= 0 && kids[nd.parent].push(id));
  const place = (id) => {
    if (!kids[id].length) {
      nodes[id].lx = leaves.length;
      leaves.push(id);
    } else {
      kids[id].forEach(place);
      nodes[id].lx = (nodes[kids[id][0]].lx + nodes[kids[id].at(-1)].lx) / 2;
    }
  };
  place(0);
  nodes.forEach((nd) => {
    nd.x = (nd.lx / Math.max(1, leaves.length - 1)) * 380 - 190;
    nd.y = nd.d * 72;
  });
  return { nodes, total: nodes.length };
})();

function schedule(t) {
  const start = 3.3, step = 1.22;
  const pos = (t - start) / step;
  const i = Math.floor(pos);
  return { i: clamp(i, -1, ROUTE.length - 1), local: pos - i, start, step, pos };
}

export default {
  id: 's02',
  num: '02',
  file: '02-roles',
  title: '局外网络，局内搜索',
  duration: 17,
  draw(ctx, t) {
    chapter(ctx, t, { num: '02', title: '局外网络，局内搜索', sub: '一局爬塔里有两类决定，交给两种不同的方法' });
    const { i: cur, local, pos } = schedule(t);
    const done = pos >= ROUTE.length;
    const kind = cur >= 0 ? ROUTE[cur] : null;
    const combat = kind && COMBAT.has(kind);

    // ---- route
    const kLine = p(t, 2.0, 1.0, ease.inOutCubic);
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.14)';
    ctx.lineWidth = 2;
    ctx.setLineDash([3, 10]);
    ctx.beginPath();
    ctx.moveTo(X0, RY);
    ctx.lineTo(lerp(X0, X1, kLine), RY);
    ctx.stroke();
    ctx.restore();
    // travelled part
    if (pos > 0) {
      const tx = lerp(X0, X1, clamp(Math.min(pos, ROUTE.length - 1) / (ROUTE.length - 1)));
      const g = ctx.createLinearGradient(X0, 0, tx, 0);
      g.addColorStop(0, rgba(C.gold, 0.15));
      g.addColorStop(1, rgba(C.gold, 0.8));
      ctx.fillStyle = g;
      ctx.fillRect(X0, RY - 1.5, tx - X0, 3);
    }
    ROUTE.forEach((k, i) => {
      const a = p(t, 2.1 + i * 0.08, 0.5, ease.outBack);
      const isCur = i === cur && !done;
      const act = isCur ? 1 : i < pos ? 0.25 : 0;
      ctx.save();
      ctx.translate(nodeX(i), RY);
      ctx.scale(a * (isCur ? 1 + 0.15 * Math.sin(Math.min(1, local) * Math.PI) : 1), a * (isCur ? 1 + 0.15 * Math.sin(Math.min(1, local) * Math.PI) : 1));
      I.mapNode(ctx, 0, 0, 28, k, { active: act, alpha: clamp(a) });
      ctx.restore();
      const lc = COMBAT.has(k) ? C.red : C.cyan;
      text(ctx, I.NODE_LABEL[k], nodeX(i), RY + 62, { size: 20, weight: 500, align: 'center', color: isCur ? lc : C.sub, alpha: clamp(a) });
    });

    // ---- panels
    const pa = p(t, 2.5, 0.7);
    const lAct = done ? 1 : kind ? (combat ? 0.35 : 1) : 0.6;
    const rAct = done ? 1 : kind ? (combat ? 1 : 0.35) : 0.6;
    const lA = lerp(0.42, 1, lAct), rA = lerp(0.42, 1, rAct);
    panel(ctx, LP.x, LP.y + (1 - pa) * 30, LP.w, LP.h, { alpha: pa * lA, glow: C.cyan, glowA: 0.1 * lAct, stroke: rgba(C.cyan, 0.15 + 0.4 * (lAct > 0.9 ? 1 : 0)), accent: C.cyan });
    panel(ctx, RP.x, RP.y + (1 - pa) * 30, RP.w, RP.h, { alpha: pa * rA, glow: C.red, glowA: 0.1 * rAct, stroke: rgba(C.red, 0.15 + 0.4 * (rAct > 0.9 ? 1 : 0)), accent: C.red });

    // headers
    const hy = LP.y + 62;
    ctx.save();
    ctx.globalAlpha *= pa * lA;
    I.brain(ctx, LP.x + 52, hy - 10, 40, C.cyan);
    text(ctx, '局外：神经网络', LP.x + 86, hy, { size: 32, weight: 700 });
    text(ctx, '选路 · 选牌 · 商店 · 篝火 · 事件 · 遗物', LP.x + 86, hy + 36, { size: 20, color: C.sub });
    ctx.restore();
    ctx.save();
    ctx.globalAlpha *= pa * rA;
    I.tree(ctx, RP.x + 52, hy - 10, 38, C.red);
    text(ctx, '局内：模拟器搜索', RP.x + 86, hy, { size: 32, weight: 700 });
    text(ctx, '每一回合怎么出牌、打谁、先后顺序', RP.x + 86, hy + 36, { size: 20, color: C.sub });
    ctx.restore();

    // beam from current node to its panel
    if (kind && !done) {
      const target = combat ? RP : LP;
      const col = combat ? C.red : C.cyan;
      const P = vCurve(nodeX(cur), RY + 76, target.x + target.w / 2, target.y - 4, 0.55);
      const bk = clamp(local / 0.3);
      const fade = 1 - clamp((local - 0.8) / 0.2);
      flow(ctx, P, ease.outCubic(bk), t, { color: col, alpha: fade, dots: 3, speed: 1.4, width: 2.5 });
    }

    // ---- left content: network + choices
    const netK = p(t, 2.8, 1.0);
    network(ctx, NET, { k: netK, t, color: C.cyan, alpha: pa * lA, pulse: !combat && kind ? 1 : 0.25, act: !combat && kind && !done ? clamp(local / 0.6) : -1 });
    const choice = kind && !combat ? CHOICES[kind] : null;
    const cx = LP.x + 420, cy0 = LP.y + 170;
    if (choice && !done) {
      const ca = clamp(local / 0.15) * (1 - clamp((local - 0.92) / 0.08));
      const best = choice.reduce((b, c, j) => (c[1] > choice[b][1] ? j : b), 0);
      choice.forEach(([label, v], j) => {
        const y = cy0 + j * 78;
        const fill = ease.outCubic(clamp((local - 0.25) / 0.35));
        const win = j === best && local > 0.62;
        text(ctx, label, cx, y, { size: 22, weight: win ? 700 : 500, color: win ? C.gold : C.ink, alpha: ca });
        scoreBar(ctx, cx, y + 22, 280, v, fill, { color: win ? C.gold : C.cyan, alpha: ca, h: 9 });
        text(ctx, v.toFixed(2), cx + 330, y + 30, { size: 20, weight: 600, fam: 'mono', color: win ? C.gold : C.sub, alpha: ca * fill, align: 'right' });
        if (win) I.check(ctx, cx + 358, y + 20, 26, C.gold);
      });
    } else if (!done) {
      text(ctx, '等待局外选择…', cx, cy0 + 70, { size: 22, color: C.dim, alpha: pa * 0.8 });
    }

    // ---- right content: mini fight + search tree
    const rx = RP.x, ry = RP.y;
    ctx.save();
    ctx.globalAlpha *= pa * rA;
    ironclad(ctx, rx + 120, ry + 230, 78);
    monster(ctx, rx + 270, ry + 232, 92, { t, color: kind === 'boss' ? '#9a3b5a' : kind === 'elite' ? '#b26a2a' : '#6b56a6' });
    const hand = [CARDS.bash, CARDS.strike, CARDS.defend];
    hand.forEach((cd, j) => {
      const chosen = combat && !done && j === 0 && local > 0.7;
      card(ctx, rx + 110 + j * 74, ry + 360 - (chosen ? 22 * clamp((local - 0.7) / 0.15) : 0), cd, {
        scale: 0.42, rot: (j - 1) * 0.08, glow: chosen ? 1 : 0, glowColor: C.red,
      });
    });
    // tree
    const ox = rx + 590, oy = ry + 132;
    const grown = combat && !done ? ease.outCubic(clamp(local / 0.75)) * TREE.total : done ? TREE.total : 2;
    TREE.nodes.forEach((nd, id) => {
      if (nd.parent < 0 || nd.order > grown) return;
      const pn = TREE.nodes[nd.parent];
      const best = isBest(id);
      const lit = combat && local > 0.62 && best;
      ctx.strokeStyle = lit ? rgba(C.gold, 0.9) : rgba(C.red, 0.35);
      ctx.lineWidth = lit ? 3 : 1.6;
      ctx.beginPath();
      ctx.moveTo(ox + pn.x, oy + pn.y);
      ctx.lineTo(ox + nd.x, oy + nd.y);
      ctx.stroke();
    });
    TREE.nodes.forEach((nd, id) => {
      if (nd.order > grown) return;
      const lit = combat && local > 0.62 && isBest(id);
      if (lit) glow(ctx, ox + nd.x, oy + nd.y, 22, C.gold, 0.7);
      ctx.beginPath();
      ctx.arc(ox + nd.x, oy + nd.y, nd.d === 0 ? 11 : 7, 0, TAU);
      ctx.fillStyle = lit ? C.gold : mix('#1a1828', C.red, 0.5);
      ctx.fill();
      ctx.strokeStyle = rgba(C.red, 0.8);
      ctx.lineWidth = 1.5;
      ctx.stroke();
    });
    // simulated counter
    if (combat && !done) {
      const n = Math.floor(ease.outCubic(clamp(local / 0.75)) * (kind === 'boss' ? 384000 : 32000));
      text(ctx, `已推演 ${n.toLocaleString('en-US')} 次`, ox, ry + 398, { size: 20, fam: 'mono', color: C.sub, align: 'center' });
    }
    ctx.restore();

    // ---- summary
    const sk = p(t, 14.4, 0.8);
    if (sk > 0) {
      text(ctx, '一个冻结的小网络，给每个选项打分', LP.x + LP.w / 2, LP.y + LP.h - 34, { size: 24, weight: 700, color: C.cyan, align: 'center', alpha: sk });
      text(ctx, '每次出牌前，在模拟器里试打几万次', RP.x + RP.w / 2, RP.y + RP.h - 34, { size: 24, weight: 700, color: C.red, align: 'center', alpha: sk });
    }
  },
};

function isBest(id) {
  // Best line: always the first child at each depth.
  let nd = TREE.nodes[id];
  while (nd.parent >= 0) {
    if (nd.i !== 0) return false;
    nd = TREE.nodes[nd.parent];
  }
  return true;
}
