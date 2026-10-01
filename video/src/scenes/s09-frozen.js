// 09 冻结小模型运行: the student freezes into one file; it takes only public
// information in and returns one choice per out-of-combat decision.
import { C, p, ease, clamp, lerp, rgba, text, glow, chapter, hash, TAU, chip, ring, rr, measure, mix } from '../engine.js';
import * as I from '../icons.js';
import { netLayout, network } from '../widgets.js';

const NC = { x: 960, y: 470 };
const NET = netLayout(NC.x - 210, NC.y - 135, 420, 270, [6, 9, 9, 1]);
const T_FREEZE = 3.0, T_LOCK = 4.7, T_FILE = 6.0, T_IN = 7.8, T_OUT = 11.6;
const FILE = { w: 660, h: 200 };
const BARRIER_X = 560;

const CRACKS = Array.from({ length: 18 }, (_, i) => {
  const a = hash(i, 1) * TAU;
  const r0 = 40 + hash(i, 2) * 200;
  const len = 40 + hash(i, 3) * 90;
  return { x: NC.x + Math.cos(a) * r0, y: NC.y + Math.sin(a) * r0 * 0.6, a: a + (hash(i, 4) - 0.5), len, d: hash(i, 5) };
});

const INPUTS = [
  ['牌组', true], ['生命', true], ['种子', false], ['金币', true], ['遗物', true],
  ['随机数', false], ['地图', true], ['楼层', true], ['未来奖励', false], ['候选选项', true],
];
const OUTPUTS = [
  [I.swords, '选路', '走精英'],
  [I.doc, '选牌', '拿「燃烧」'],
  [I.bag, '商店', '删一张「打击」'],
  [I.campfire, '篝火', '休息'],
  [I.question, '事件', '离开'],
  [I.chest, 'Boss 遗物', '选第 2 个'],
];

export default {
  id: 's09',
  num: '09',
  file: '09-frozen',
  title: '冻结：一个文件跑全程',
  duration: 16.5,
  draw(ctx, t) {
    chapter(ctx, t, { num: '09', title: '冻结：一个文件跑全程', sub: '训练结束就不再改动，所有局外选择都交给它' });

    const frozen = p(t, T_FREEZE, 1.6, ease.inOutQuad);
    const toFile = p(t, T_FILE, 0.9, ease.inOutCubic);

    // ---- network that freezes
    if (toFile < 1) {
      const sc = lerp(1, 0.3, toFile);
      ctx.save();
      ctx.globalAlpha *= 1 - toFile;
      ctx.translate(NC.x, NC.y);
      ctx.scale(sc, sc);
      ctx.translate(-NC.x, -NC.y);
      glow(ctx, NC.x, NC.y, 340, mix(C.cyan, '#bfe9ff', frozen), 0.12 + 0.12 * frozen);
      // frosted plate
      if (frozen > 0) {
        rr(ctx, NC.x - 270, NC.y - 175, 540, 350, 28);
        ctx.fillStyle = rgba('#bfe9ff', 0.06 * frozen);
        ctx.fill();
        ctx.strokeStyle = rgba('#d8f3ff', 0.35 * frozen);
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      network(ctx, NET, { k: p(t, 2.0, 0.9), t: t * (1 - frozen), color: mix(C.cyan, '#cdefff', frozen), pulse: 1 - frozen, frozen, act: frozen < 0.5 ? (t * 0.7) % 1 : -1 });
      // ice cracks
      CRACKS.forEach((c) => {
        const k = clamp((frozen - c.d * 0.5) / 0.5);
        if (k <= 0) return;
        ctx.save();
        ctx.strokeStyle = rgba('#e6f7ff', 0.38 * k);
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(c.x, c.y);
        const ex = c.x + Math.cos(c.a) * c.len * k, ey = c.y + Math.sin(c.a) * c.len * k;
        ctx.lineTo(ex, ey);
        ctx.lineTo(ex + Math.cos(c.a + 0.8) * 18 * k, ey + Math.sin(c.a + 0.8) * 18 * k);
        ctx.stroke();
        ctx.restore();
      });
      for (let i = 0; i < 10; i++) {
        const k = clamp((frozen - hash(i, 9) * 0.6) / 0.4);
        if (k <= 0) continue;
        const a = hash(i, 8) * TAU;
        I.snowflake(ctx, NC.x + Math.cos(a) * 250, NC.y + Math.sin(a) * 150, 22 * k, rgba('#dff4ff', 0.8));
      }
      ctx.restore();
    }
    // lock drop
    const lk = p(t, T_LOCK, 0.45, ease.outBack);
    if (lk > 0 && toFile < 1) {
      const y = lerp(150, NC.y - 205, lk);
      ctx.save();
      ctx.globalAlpha *= clamp(lk) * (1 - toFile);
      glow(ctx, NC.x, y, 70, '#bfe9ff', 0.4);
      I.lock(ctx, NC.x, y, 64, '#e6f7ff');
      ctx.restore();
      ring(ctx, NC.x, NC.y - 205, clamp((t - T_LOCK - 0.4) / 0.7), { r0: 30, r1: 140, color: '#cdefff' });
    }
    const fa = p(t, T_FREEZE + 0.6, 0.6) * (1 - p(t, T_FILE - 0.2, 0.4));
    text(ctx, '冻结：之后不再训练，也不再修改', NC.x, NC.y + 240, { size: 28, weight: 700, align: 'center', color: '#d8f3ff', alpha: fa });

    // ---- file card
    const fk = p(t, T_FILE + 0.4, 0.8, ease.outBack);
    if (fk > 0) {
      const w = FILE.w * clamp(fk, 0, 1.1), h = FILE.h;
      const x = NC.x - w / 2, y = NC.y - h / 2;
      ctx.save();
      ctx.globalAlpha *= clamp(fk);
      glow(ctx, NC.x, NC.y, 380, '#bfe9ff', 0.14, 1, 0.5);
      rr(ctx, x, y, w, h, 22);
      const g = ctx.createLinearGradient(0, y, 0, y + h);
      g.addColorStop(0, '#20314a');
      g.addColorStop(1, '#121a2c');
      ctx.fillStyle = g;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = rgba('#cdefff', 0.6);
      ctx.stroke();
      if (fk > 0.8) {
        I.doc(ctx, x + 70, NC.y - 26, 64, '#cdefff');
        I.lock(ctx, x + 92, NC.y + 2, 26, C.gold);
        text(ctx, 'distill2_frozen.pt', x + 130, NC.y - 22, { size: 34, weight: 700, fam: 'mono', color: '#eaf7ff' });
        let cx = x + 130;
        [['17 MB', C.cyan], ['11195 → 384 → 1', C.cyan], ['sha256 90b9…fa2b', C.dim]].forEach(([s, col]) => {
          cx += chip(ctx, cx, NC.y + 38, s, { color: col, size: 16, fam: 'mono', padX: 11 }) + 10;
        });
      }
      ctx.restore();
    }

    // ---- inputs: public information only
    const ba = p(t, T_IN - 0.3, 0.5);
    if (ba > 0) {
      const g = ctx.createLinearGradient(0, NC.y - 170, 0, NC.y + 170);
      g.addColorStop(0, rgba(C.cyan, 0));
      g.addColorStop(0.5, rgba(C.cyan, 0.8 * ba));
      g.addColorStop(1, rgba(C.cyan, 0));
      ctx.fillStyle = g;
      ctx.fillRect(BARRIER_X - 2, NC.y - 170, 4, 340);
      glow(ctx, BARRIER_X, NC.y, 160, C.cyan, 0.12 * ba, 0.15, 1);
      text(ctx, '只放进公开信息', BARRIER_X, NC.y - 192, { size: 22, weight: 700, color: C.cyan, align: 'center', alpha: ba });
    }
    INPUTS.forEach(([label, ok], i) => {
      const t0 = T_IN + i * 0.34;
      const lane = [NC.y - 100, NC.y, NC.y + 100][i % 3];
      const k = clamp((t - t0) / 1.5);
      if (k <= 0 || k >= 1) return;
      const w = measure(ctx, label, 20, 600) + 30;
      const startX = 150, hitX = BARRIER_X - w / 2 - 8, endX = NC.x - FILE.w / 2 + 40;
      let x, a = 1, sc = 1;
      if (ok) {
        x = lerp(startX, endX, ease.inOutQuad(k));
        if (k > 0.75) { a = 1 - (k - 0.75) / 0.25; sc = 1 - 0.5 * (k - 0.75) / 0.25; }
      } else {
        const k1 = clamp(k / 0.55);
        x = k < 0.55 ? lerp(startX, hitX, ease.inQuad(k1)) : lerp(hitX, hitX - 120, ease.outCubic((k - 0.55) / 0.45));
        if (k > 0.55) {
          a = 1 - (k - 0.55) / 0.45;
          I.cross(ctx, BARRIER_X, lane, 36, C.red);
          ring(ctx, BARRIER_X, lane, (k - 0.55) / 0.45, { r0: 10, r1: 60, color: C.red });
        }
      }
      ctx.save();
      ctx.translate(x, lane);
      ctx.scale(sc, sc);
      chip(ctx, 0, 0, label, { color: ok ? C.cyan : C.red, size: 20, align: 'center', alpha: a, weight: 600, fill: rgba(ok ? C.cyan : C.red, 0.16) });
      ctx.restore();
    });

    // ---- what it can and cannot see
    const seen = INPUTS.filter(([, ok]) => ok).map(([l]) => l);
    const hidden = INPUTS.filter(([, ok]) => !ok).map(([l]) => l);
    const ra = p(t, T_IN + 1.0, 0.5);
    const rb = p(t, T_IN + 2.2, 0.5);
    ctx.save();
    ctx.globalAlpha *= ra;
    I.check(ctx, 690, 692, 26, C.cyan);
    text(ctx, '看得到：' + seen.join(' · '), 716, 700, { size: 22, weight: 500 });
    ctx.restore();
    ctx.save();
    ctx.globalAlpha *= rb;
    I.cross(ctx, 690, 748, 24, C.red);
    text(ctx, '看不到：' + hidden.join(' · '), 716, 756, { size: 22, weight: 500, color: C.sub });
    ctx.restore();

    // ---- outputs: choices
    const oa = p(t, T_OUT - 0.3, 0.5);
    text(ctx, '输出：一个选择', 1490, NC.y - 192, { size: 22, weight: 700, color: C.gold, align: 'left', alpha: oa });
    OUTPUTS.forEach(([icon, kind, what], i) => {
      const k = p(t, T_OUT + i * 0.38, 0.5, ease.outCubic);
      if (k <= 0) return;
      const y = NC.y - 140 + i * 56;
      const x = lerp(NC.x + FILE.w / 2 - 40, 1490, k);
      ctx.save();
      ctx.globalAlpha *= k;
      rr(ctx, x, y - 22, 300, 44, 12);
      ctx.fillStyle = 'rgba(255,255,255,0.05)';
      ctx.fill();
      ctx.strokeStyle = rgba(C.gold, 0.35);
      ctx.lineWidth = 1.5;
      ctx.stroke();
      icon(ctx, x + 26, y, 22, C.gold);
      text(ctx, kind, x + 50, y + 7, { size: 18, color: C.sub });
      text(ctx, what, x + 140, y + 7, { size: 19, weight: 700 });
      ctx.restore();
    });
    const ck = p(t, T_OUT + 2.6, 0.6);
    text(ctx, '同一个局面输进去，永远得到同一个选择', 960, 900, { size: 28, weight: 500, color: C.sub, align: 'center', alpha: ck });
  },
};
