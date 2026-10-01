// 07 分叉改进: one decision point, two futures from the same seed and random
// numbers; then many such forks are tallied before an improvement is adopted.
import { C, p, ease, clamp, lerp, rgba, text, glow, chapter, hash, TAU, chip, ring, measure } from '../engine.js';
import * as I from '../icons.js';

const TRUNK_Y = 580, TOP_Y = 420, BOT_Y = 740;
const TRUNK = [['start', 190], ['fight', 310], ['elite', 430]];
const FORK_X = 570;
const BRANCH = [['shop', 800], ['fight', 950], ['boss', 1100], ['elite', 1250], ['fight', 1400]];
const HEART_X = 1580;
const T_TRUNK = 2.4, T_FORK = 3.9, T_RUN = 4.7, T_RUN_D = 2.8, T_END = 7.7;
const T_SHRINK = 9.6;

// Mini forks: [baseline win, changed win]
const MINI = Array.from({ length: 24 }, (_, i) => {
  const r = hash(i, 11);
  if ([2, 7, 9, 14, 19, 22].includes(i)) return [false, true];
  if ([5, 17].includes(i)) return [true, false];
  return r > 0.55 ? [true, true] : [false, false];
});

function branchPath(y) {
  // bezier from the fork node to the branch line, then straight
  return { c: [{ x: FORK_X, y: TRUNK_Y }, { x: FORK_X + 90, y: TRUNK_Y }, { x: FORK_X + 60, y }, { x: FORK_X + 170, y }] };
}

function strokeBranch(ctx, y, k, col, w) {
  const { c } = branchPath(y);
  const total = 1 + (HEART_X - c[3].x) / 300;
  const k1 = Math.min(1, (k * total));
  ctx.save();
  ctx.strokeStyle = col;
  ctx.lineWidth = w;
  ctx.lineCap = 'round';
  ctx.beginPath();
  for (let i = 0; i <= 24; i++) {
    const u = (i / 24) * k1;
    const q = bezPt(c, u);
    i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y);
  }
  if (k * total > 1) ctx.lineTo(lerp(c[3].x, HEART_X, clamp((k * total - 1) / (total - 1))), y);
  ctx.stroke();
  ctx.restore();
}

function bezPt(P, k) {
  const [a, b, c, d] = P;
  const u = 1 - k;
  return {
    x: u * u * u * a.x + 3 * u * u * k * b.x + 3 * u * k * k * c.x + k * k * k * d.x,
    y: u * u * u * a.y + 3 * u * u * k * b.y + 3 * u * k * k * c.y + k * k * k * d.y,
  };
}

function headPos(y, k) {
  const { c } = branchPath(y);
  const total = 1 + (HEART_X - c[3].x) / 300;
  const kk = k * total;
  if (kk <= 1) return bezPt(c, kk);
  return { x: lerp(c[3].x, HEART_X, clamp((kk - 1) / (total - 1))), y };
}

function drawStory(ctx, t) {
  // seed chips
  const sa = p(t, 2.1, 0.5);
  let cx = 150;
  cx += chip(ctx, cx, 300, '种子 3900012720', { color: C.violet, size: 22, alpha: sa, fam: 'mono', icon: I.dice }) + 12;
  chip(ctx, cx, 300, '同一串随机数、同一个战斗搜索', { color: C.sub, size: 20, alpha: p(t, 2.4, 0.5) });

  // trunk
  const tk = p(t, T_TRUNK, 1.4, ease.inOutQuad);
  ctx.save();
  ctx.strokeStyle = rgba(C.gold, 0.7);
  ctx.lineWidth = 4;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(TRUNK[0][1], TRUNK_Y);
  ctx.lineTo(lerp(TRUNK[0][1], FORK_X, tk), TRUNK_Y);
  ctx.stroke();
  ctx.restore();
  TRUNK.forEach(([k, x], i) => {
    const a = p(t, T_TRUNK + i * 0.35, 0.45, ease.outBack);
    ctx.save();
    ctx.translate(x, TRUNK_Y);
    ctx.scale(a, a);
    I.mapNode(ctx, 0, 0, 26, k, { active: 0.3, alpha: clamp(a) });
    ctx.restore();
  });
  // fork node
  const fa = p(t, T_FORK - 0.3, 0.6, ease.outBack);
  ctx.save();
  ctx.translate(FORK_X, TRUNK_Y);
  ctx.scale(fa, fa);
  I.mapNode(ctx, 0, 0, 36, 'rest', { active: 1, alpha: clamp(fa) });
  ctx.restore();
  text(ctx, '篝火：二选一', FORK_X - 30, TRUNK_Y - 56, { size: 22, weight: 700, align: 'center', color: C.orange, alpha: clamp(fa) });
  ring(ctx, FORK_X, TRUNK_Y, clamp((t - T_FORK) / 0.9), { r0: 36, r1: 130, color: C.orange });

  // branches
  const rk = p(t, T_FORK, T_RUN_D + (T_RUN - T_FORK), ease.inOutSine);
  const lines = [
    { y: TOP_Y, label: '升级「武装」', hp: 37, win: false, col: C.blue },
    { y: BOT_Y, label: '休息：回复生命', hp: 53, win: true, col: C.green },
  ];
  lines.forEach((ln, li) => {
    strokeBranch(ctx, ln.y, rk, rgba(ln.col, 0.75), 4);
    // nodes on the branch
    BRANCH.forEach(([k, x]) => {
      const h = headPos(ln.y, rk);
      const reached = h.x >= x - 2;
      ctx.save();
      ctx.translate(x, ln.y);
      const s = reached ? 1 : 0;
      ctx.scale(s, s);
      I.mapNode(ctx, 0, 0, 22, k, { active: reached ? 0.25 : 0, alpha: s });
      ctx.restore();
    });
    // heart at the end
    const reachedHeart = rk >= 1;
    const hk = p(t, T_END - 0.4, 0.5, ease.outBack);
    ctx.save();
    ctx.translate(HEART_X, ln.y);
    ctx.scale(hk, hk);
    I.mapNode(ctx, 0, 0, 32, 'heart', { alpha: clamp(hk), active: reachedHeart ? 0.6 : 0 });
    ctx.restore();
    // travelling light
    if (rk > 0 && rk < 1) {
      const h = headPos(ln.y, rk);
      glow(ctx, h.x, h.y, 34, ln.col, 0.9);
      glow(ctx, h.x, h.y, 12, '#ffffff', 0.9);
    }
    // label chip near the start of the branch
    chip(ctx, FORK_X + 190, ln.y + (li ? 50 : -48), ln.label, { color: ln.col, size: 22, alpha: p(t, T_FORK + 0.3, 0.5), weight: 700 });
    // HP readout follows the light
    const hpK = p(t, T_RUN + 0.6, 0.4);
    if (hpK > 0 && rk < 1) {
      const h = headPos(ln.y, rk);
      const hp = Math.round(lerp(li ? 66 : 46, ln.hp, clamp((rk - 0.2) / 0.8)));
      text(ctx, `${hp} 血`, h.x, ln.y + (li ? 44 : -26), { size: 18, weight: 700, fam: 'mono', align: 'center', color: C.ink, alpha: hpK });
    }
    // outcome
    const ok = p(t, T_END, 0.5, ease.outBack);
    if (ok > 0) {
      text(ctx, `进心脏时 ${ln.hp} 血`, HEART_X - 52, ln.y + (li ? 62 : -46), { size: 20, color: C.sub, align: 'right', alpha: clamp(ok) });
      ctx.save();
      ctx.translate(HEART_X + 78, ln.y);
      ctx.scale(ok, ok);
      if (ln.win) {
        glow(ctx, 0, 0, 70, C.gold, 0.5);
        I.crown(ctx, 0, -4, 44, C.gold);
      } else {
        I.cross(ctx, 0, 0, 40, C.red);
      }
      ctx.restore();
      text(ctx, ln.win ? '击败心脏 · 剩 7 血' : '倒在心脏前', HEART_X + 78, ln.y + 50, { size: 20, weight: 700, align: 'center', color: ln.win ? C.gold : C.red, alpha: clamp(ok) });
    }
  });
}

export default {
  id: 's07',
  num: '07',
  file: '07-fork',
  title: '分叉对比：只改一个选择',
  duration: 19,
  draw(ctx, t) {
    chapter(ctx, t, { num: '07', title: '分叉对比：只改一个选择', sub: '同一个种子、同一串随机数，让两条未来各自打到底，比结局' });

    // ---- the story, later shrunk to the corner
    const sk = p(t, T_SHRINK, 1.0, ease.inOutCubic);
    const s = lerp(1, 0.46, sk);
    ctx.save();
    ctx.translate(lerp(0, 130 - 150 * 0.46, sk), lerp(0, 262 - 280 * 0.46, sk));
    ctx.scale(s, s);
    drawStory(ctx, t);
    ctx.restore();

    if (t < T_SHRINK - 0.2) {
      const ck = p(t, T_END + 0.6, 0.6) * (1 - p(t, T_SHRINK - 0.6, 0.4));
      text(ctx, '一次分叉只说明这一局，不能说明这条规则', 960, 910, { size: 26, weight: 500, color: C.sub, align: 'center', alpha: ck });
    }

    // ---- many forks
    const gx = 960, gy = 286, cw = 104, rh = 84;
    const ga = p(t, T_SHRINK + 0.5, 0.6);
    text(ctx, '在一批固定种子上，每局都做同样的分叉', gx, gy - 24, { size: 22, weight: 700, alpha: ga });
    text(ctx, '示意', 1790, gy - 24, { size: 16, color: C.dim, align: 'right', alpha: ga });
    let rescued = 0, lost = 0;
    const tallies = [];
    MINI.forEach(([base, alt], i) => {
      const col = i % 8, row = Math.floor(i / 8);
      const x = gx + col * cw + 20, y = gy + 34 + row * rh;
      const ak = p(t, T_SHRINK + 0.6 + i * 0.03, 0.4);
      if (ak <= 0) return;
      const rt = T_SHRINK + 1.4 + i * 0.1;
      const res = p(t, rt, 0.3);
      ctx.save();
      ctx.globalAlpha *= ak;
      ctx.strokeStyle = 'rgba(255,255,255,0.35)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + 26, y);
      ctx.bezierCurveTo(x + 40, y, x + 36, y - 18, x + 56, y - 18);
      ctx.moveTo(x + 26, y);
      ctx.bezierCurveTo(x + 40, y, x + 36, y + 18, x + 56, y + 18);
      ctx.stroke();
      const dot = (yy, win) => {
        ctx.beginPath();
        ctx.arc(x + 62, yy, 7, 0, TAU);
        ctx.fillStyle = res > 0 ? rgba(win ? C.green : C.red, 0.35 + 0.65 * res) : 'rgba(255,255,255,0.15)';
        ctx.fill();
      };
      dot(y - 18, base);
      dot(y + 18, alt);
      const kind = !base && alt ? 'r' : base && !alt ? 'l' : 'n';
      if (kind !== 'n' && res > 0) {
        glow(ctx, x + 40, y, 50, kind === 'r' ? C.green : C.red, 0.35 * res);
        ring(ctx, x + 40, y, clamp((t - rt) / 0.6), { r0: 20, r1: 50, color: kind === 'r' ? C.green : C.red, width: 2 });
      }
      if (kind === 'n' && res > 0) {
        ctx.beginPath();
        ctx.roundRect(x - 8, y - 32, 88, 64, 10);
        ctx.fillStyle = rgba('#07070f', 0.5 * res);
        ctx.fill();
      }
      ctx.restore();
      if (kind !== 'n') tallies.push({ kind, x: x + 40, y, t: rt + 0.35, idx: kind === 'r' ? rescued++ : lost++ });
    });
    // legend
    const la = p(t, T_SHRINK + 1.0, 0.5);
    ctx.save();
    ctx.globalAlpha *= la;
    text(ctx, '上：原选择的结局', gx + 20, gy + 296, { size: 17, color: C.sub });
    text(ctx, '下：改了之后的结局', gx + 200, gy + 296, { size: 17, color: C.sub });
    ctx.restore();

    // tallies
    const tyR = 660, tyL = 720, tx0 = 1100;
    const ta = p(t, T_SHRINK + 1.2, 0.5);
    text(ctx, '救回', gx + 20, tyR + 8, { size: 24, weight: 700, color: C.green, alpha: ta });
    text(ctx, '原来输、改了赢', gx + 20, tyR + 34, { size: 15, color: C.sub, alpha: ta });
    text(ctx, '丢失', gx + 20, tyL + 26, { size: 24, weight: 700, color: C.red, alpha: ta });
    text(ctx, '原来赢、改了输', gx + 20, tyL + 52, { size: 15, color: C.sub, alpha: ta });
    tallies.forEach((d) => {
      const k = p(t, d.t, 0.5, ease.inOutCubic);
      if (k <= 0) return;
      const tx = tx0 + d.idx * 46, ty = d.kind === 'r' ? tyR : tyL + 18;
      const x = lerp(d.x, tx, k), y = lerp(d.y, ty, k) - Math.sin(k * Math.PI) * 40;
      const col = d.kind === 'r' ? C.green : C.red;
      glow(ctx, x, y, 26, col, 0.6);
      ctx.beginPath();
      ctx.arc(x, y, 13, 0, TAU);
      ctx.fillStyle = col;
      ctx.fill();
    });
    const vk = p(t, T_SHRINK + 4.2, 0.5, ease.outBack);
    if (vk > 0) {
      ctx.save();
      ctx.translate(1640, 690);
      ctx.rotate(-0.08);
      ctx.scale(lerp(1.6, 1, clamp(vk)), lerp(1.6, 1, clamp(vk)));
      ctx.globalAlpha *= clamp(vk);
      ctx.strokeStyle = C.gold;
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.roundRect(-92, -38, 184, 76, 12);
      ctx.stroke();
      text(ctx, '采纳', 0, 16, { size: 42, weight: 900, fam: 'serif', align: 'center', color: C.gold });
      ctx.restore();
      text(ctx, '救回 > 丢失', 1640, 760, { size: 18, color: C.gold, align: 'center', alpha: clamp(vk) });
    }

    // left explanation under the small story
    const ex = [
      ['1', '找到一个可以改的选择'],
      ['2', '同一个种子，两条未来各自打到底'],
      ['3', '换一批种子重复，统计救回和丢失'],
    ];
    ex.forEach(([n, s2], i) => {
      const k = p(t, T_SHRINK + 0.8 + i * 0.35, 0.5);
      const y = 600 + i * 58;
      ctx.save();
      ctx.globalAlpha *= k;
      ctx.beginPath();
      ctx.arc(150, y - 8, 17, 0, TAU);
      ctx.fillStyle = rgba(C.gold, 0.18);
      ctx.fill();
      ctx.strokeStyle = C.gold;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      text(ctx, n, 150, y - 1, { size: 18, weight: 700, fam: 'mono', align: 'center', color: C.gold });
      text(ctx, s2, 184, y, { size: 24, weight: 500 });
      ctx.restore();
    });

    // ---- the teacher accumulates adopted improvements
    const arms = ['原始策略', '篝火休息', '搜索树复用', '价值表选牌', '攻略规则', '高手规则', '主动找精英', 'Boss 加搜索', '盾矛加搜索', '……'];
    const lk = p(t, T_SHRINK + 5.0, 0.5);
    text(ctx, '老师 =', 130, 868, { size: 28, weight: 900, fam: 'serif', color: C.gold, alpha: lk });
    let ax = 236;
    arms.forEach((a, i) => {
      const k = p(t, T_SHRINK + 5.2 + i * 0.22, 0.45, ease.outBack);
      const label = i === 0 ? a : i === arms.length - 1 ? a : `+ ${a}`;
      const w = measure(ctx, label, 20, 600) + 30;
      chip(ctx, ax, 858 + (1 - clamp(k)) * 12, label, { color: i === 0 ? C.sub : C.gold, size: 20, alpha: clamp(k), weight: 600, padX: 15 });
      ax += w + 10;
    });
  },
};
