// Composite widgets shared by several segments: game cards, neural network,
// score bars, HP bar, little game-state readouts.
import { C, TAU, clamp, lerp, ease, hash, rgba, mix, text, glow, rr } from './engine.js';
import * as I from './icons.js';

export const CW = 150;
export const CH = 206;

const TYPE = {
  attack: { color: C.attack, label: '攻击', icon: (c, x, y, s, col) => I.sword(c, x, y, s, col) },
  skill: { color: C.skill, label: '技能', icon: (c, x, y, s, col) => I.shield(c, x, y, s, col, { fill: true }) },
  power: { color: C.power, label: '能力', icon: (c, x, y, s, col) => I.flame(c, x, y, s, col) },
};

// Ironclad cards used across the segments (names follow the Chinese release).
export const CARDS = {
  strike: { name: '打击', cost: 1, type: 'attack', desc: '造成 6 点伤害' },
  defend: { name: '防御', cost: 1, type: 'skill', desc: '获得 5 点格挡' },
  bash: { name: '痛击', cost: 2, type: 'attack', desc: '伤害 + 易伤' },
  shrug: { name: '耸肩无视', cost: 1, type: 'skill', desc: '格挡 + 抽 1 张' },
  pommel: { name: '剑柄打击', cost: 1, type: 'attack', desc: '伤害 + 抽 1 张' },
  inflame: { name: '燃烧', cost: 1, type: 'power', desc: '获得 2 点力量' },
  heavy: { name: '重刃', cost: 2, type: 'attack', desc: '力量 ×3 生效' },
  whirl: { name: '旋风斩', cost: 'X', type: 'attack', desc: '对所有敌人' },
  metal: { name: '金属化', cost: 1, type: 'power', desc: '回合末格挡' },
  offering: { name: '祭品', cost: 0, type: 'skill', desc: '失血换能量' },
  demon: { name: '恶魔形态', cost: 3, type: 'power', desc: '每回合加力量' },
  armaments: { name: '武装', cost: 1, type: 'skill', desc: '格挡 + 升级' },
  cleave: { name: '顺劈斩', cost: 1, type: 'attack', desc: '对所有敌人' },
  twin: { name: '双重打击', cost: 1, type: 'attack', desc: '伤害 ×2' },
  limit: { name: '突破极限', cost: 1, type: 'skill', desc: '力量翻倍' },
};

// Draw a card centred at (x, y). o: scale, rot, alpha, glow (0..1), glowColor, back (0..1 flip).
export function card(ctx, x, y, spec, o = {}) {
  const a = o.alpha ?? 1;
  if (a <= 0.002) return;
  const s = o.scale ?? 1;
  const flip = o.flip ?? 0; // 0 = face up, 1 = face down; animates through edge-on
  const sx = Math.abs(Math.cos(flip * Math.PI));
  const showBack = flip > 0.5;
  const ty = TYPE[spec.type] ?? TYPE.attack;
  const col = ty.color;
  ctx.save();
  ctx.globalAlpha *= a;
  ctx.translate(x, y);
  if (o.rot) ctx.rotate(o.rot);
  ctx.scale(s * Math.max(0.02, sx), s);
  const w = CW, h = CH;
  if (o.glow) glow(ctx, 0, 0, 170, o.glowColor ?? C.gold, 0.55 * o.glow, 0.85, 1.05);
  // Shadow
  ctx.save();
  ctx.fillStyle = 'rgba(0,0,0,0.45)';
  rr(ctx, -w / 2 + 6, -h / 2 + 10, w, h, 14);
  ctx.fill();
  ctx.restore();
  if (showBack) {
    rr(ctx, -w / 2, -h / 2, w, h, 14);
    const g = ctx.createLinearGradient(0, -h / 2, 0, h / 2);
    g.addColorStop(0, '#2b2347');
    g.addColorStop(1, '#151126');
    ctx.fillStyle = g;
    ctx.fill();
    ctx.lineWidth = 3;
    ctx.strokeStyle = rgba(C.gold, 0.55);
    ctx.stroke();
    ctx.strokeStyle = rgba(C.gold, 0.35);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, -h * 0.32);
    ctx.lineTo(w * 0.3, 0);
    ctx.lineTo(0, h * 0.32);
    ctx.lineTo(-w * 0.3, 0);
    ctx.closePath();
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, 0, 14, 0, TAU);
    ctx.stroke();
    ctx.restore();
    return;
  }
  // Body
  rr(ctx, -w / 2, -h / 2, w, h, 14);
  const body = ctx.createLinearGradient(0, -h / 2, 0, h / 2);
  body.addColorStop(0, mix(col, '#1a1626', 0.55));
  body.addColorStop(1, mix(col, '#0e0c16', 0.8));
  ctx.fillStyle = body;
  ctx.fill();
  ctx.lineWidth = 3;
  ctx.strokeStyle = o.border ?? mix(col, '#ffffff', 0.15);
  ctx.stroke();
  // Art window
  rr(ctx, -w / 2 + 14, -h / 2 + 44, w - 28, 82, 8);
  const art = ctx.createRadialGradient(0, -h / 2 + 85, 4, 0, -h / 2 + 85, 70);
  art.addColorStop(0, mix(col, '#000000', 0.35));
  art.addColorStop(1, '#0b0a12');
  ctx.fillStyle = art;
  ctx.fill();
  ctx.strokeStyle = rgba('#000000', 0.5);
  ctx.lineWidth = 1.5;
  ctx.stroke();
  ty.icon(ctx, 0, -h / 2 + 85, 50, mix(col, '#ffffff', 0.35));
  // Name banner
  rr(ctx, -w / 2 + 8, -h / 2 + 12, w - 16, 28, 6);
  ctx.fillStyle = mix(col, '#0b0a12', 0.35);
  ctx.fill();
  const nameSize = spec.name.length > 3 ? 17 : 19;
  text(ctx, spec.name, 6, -h / 2 + 32, { size: nameSize, weight: 700, align: 'center', color: '#fff6ea' });
  // Type + description
  text(ctx, ty.label, 0, -h / 2 + 146, { size: 13, weight: 500, align: 'center', color: rgba('#ffffff', 0.55) });
  if (spec.desc) text(ctx, spec.desc, 0, -h / 2 + 176, { size: 15, weight: 500, align: 'center', color: '#efe6d8' });
  if (spec.up) text(ctx, '+', w / 2 - 16, -h / 2 + 32, { size: 20, weight: 900, align: 'center', color: C.green });
  // Cost orb
  const ox = -w / 2 + 6, oy = -h / 2 + 6;
  ctx.beginPath();
  ctx.arc(ox, oy, 17, 0, TAU);
  const og = ctx.createRadialGradient(ox - 5, oy - 6, 2, ox, oy, 17);
  og.addColorStop(0, '#ffb070');
  og.addColorStop(0.6, '#e2502e');
  og.addColorStop(1, '#7a1a12');
  ctx.fillStyle = og;
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = '#2a0e08';
  ctx.stroke();
  text(ctx, String(spec.cost), ox, oy + 7.5, { size: 20, weight: 900, align: 'center', color: '#fff', fam: 'mono' });
  if (o.dim) {
    rr(ctx, -w / 2, -h / 2, w, h, 14);
    ctx.fillStyle = `rgba(6,6,12,${0.6 * o.dim})`;
    ctx.fill();
  }
  if (o.outline) {
    rr(ctx, -w / 2 - 5, -h / 2 - 5, w + 10, h + 10, 18);
    ctx.lineWidth = 3;
    ctx.strokeStyle = rgba(o.glowColor ?? C.gold, o.outline);
    ctx.stroke();
  }
  ctx.restore();
}

// ---------------------------------------------------------------- neural net

// Build a layout once: layers = node counts per column.
export function netLayout(x, y, w, h, layers) {
  const cols = layers.map((n, li) => {
    const cx = x + (layers.length === 1 ? w / 2 : (li / (layers.length - 1)) * w);
    const gap = Math.min(46, h / Math.max(1, n - 1));
    const span = gap * (n - 1);
    return Array.from({ length: n }, (_, i) => ({ x: cx, y: y + h / 2 - span / 2 + i * gap }));
  });
  const edges = [];
  for (let l = 0; l < cols.length - 1; l++)
    for (let i = 0; i < cols[l].length; i++)
      for (let j = 0; j < cols[l + 1].length; j++) edges.push({ l, a: cols[l][i], b: cols[l + 1][j], s: hash(l, i, j) });
  return { cols, edges };
}

// k: build-in progress, act: activation wave position (0..1 across layers, <0 none),
// t for pulses, color, frozen (0..1) tint.
export function network(ctx, net, o = {}) {
  const a = o.alpha ?? 1;
  if (a <= 0.002) return;
  const col = o.color ?? C.cyan;
  const k = o.k ?? 1;
  const t = o.t ?? 0;
  const L = net.cols.length;
  const frozen = o.frozen ?? 0;
  const nodeCol = mix(col, '#d8f4ff', frozen * 0.7);
  ctx.save();
  ctx.globalAlpha *= a;
  // edges
  for (const e of net.edges) {
    const ek = clamp(k * (L - 1) - e.l);
    if (ek <= 0) continue;
    const w = 0.35 + e.s * 0.9;
    ctx.strokeStyle = rgba(nodeCol, (0.05 + 0.13 * e.s) * ek * (o.edgeA ?? 1));
    ctx.lineWidth = w;
    ctx.beginPath();
    ctx.moveTo(e.a.x, e.a.y);
    ctx.lineTo(lerp(e.a.x, e.b.x, ek), lerp(e.a.y, e.b.y, ek));
    ctx.stroke();
  }
  // pulses
  if (o.pulse) {
    const speed = o.pulseSpeed ?? 0.9;
    for (let i = 0; i < net.edges.length; i++) {
      const e = net.edges[i];
      if (e.s < 0.62) continue;
      const ph = (t * speed + e.s * 3.7) % 1;
      const layerPh = (ph * (L - 1)) - e.l;
      if (layerPh < 0 || layerPh > 1) continue;
      const qx = lerp(e.a.x, e.b.x, layerPh), qy = lerp(e.a.y, e.b.y, layerPh);
      glow(ctx, qx, qy, 9, col, 0.7 * o.pulse);
    }
  }
  // activation wave
  const act = o.act ?? -1;
  // nodes
  net.cols.forEach((colNodes, li) => {
    const nk = clamp(k * L - li);
    if (nk <= 0) return;
    colNodes.forEach((n, ni) => {
      const r = (o.r ?? 7) * (li === L - 1 && colNodes.length === 1 ? 1.6 : 1);
      let lit = 0;
      if (act >= 0) {
        const pos = act * (L - 1);
        lit = Math.max(0, 1 - Math.abs(pos - li) * 1.4) * (0.5 + 0.5 * hash(li, ni));
      }
      if (lit > 0.05) glow(ctx, n.x, n.y, r * 4, col, lit * 0.9);
      ctx.beginPath();
      ctx.arc(n.x, n.y, r * ease.outBack(nk), 0, TAU);
      ctx.fillStyle = mix('#14131f', col, 0.15 + lit * 0.7);
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = rgba(nodeCol, 0.85);
      ctx.stroke();
    });
  });
  ctx.restore();
}

// ---------------------------------------------------------------- readouts

export function hpBar(ctx, x, y, w, hp, max, o = {}) {
  const h = o.h ?? 14;
  const a = o.alpha ?? 1;
  ctx.save();
  ctx.globalAlpha *= a;
  rr(ctx, x, y, w, h, h / 2);
  ctx.fillStyle = 'rgba(0,0,0,0.5)';
  ctx.fill();
  ctx.strokeStyle = 'rgba(255,255,255,0.12)';
  ctx.lineWidth = 1.5;
  ctx.stroke();
  const f = clamp(hp / max);
  if (f > 0) {
    rr(ctx, x + 2, y + 2, (w - 4) * f, h - 4, (h - 4) / 2);
    const g = ctx.createLinearGradient(0, y, 0, y + h);
    g.addColorStop(0, o.color2 ?? '#ff7a6e');
    g.addColorStop(1, o.color ?? '#c42c2a');
    ctx.fillStyle = g;
    ctx.fill();
  }
  if (o.label !== false)
    text(ctx, `${Math.round(hp)}/${max}`, x + w / 2, y + h - 1.5, { size: h * 0.95, weight: 700, fam: 'mono', align: 'center', color: '#fff' });
  ctx.restore();
}

// Horizontal score bar with numeric label. k animates fill.
export function scoreBar(ctx, x, y, w, value, k, o = {}) {
  const h = o.h ?? 10;
  const col = o.color ?? C.cyan;
  ctx.save();
  ctx.globalAlpha *= o.alpha ?? 1;
  rr(ctx, x, y - h / 2, w, h, h / 2);
  ctx.fillStyle = 'rgba(255,255,255,0.07)';
  ctx.fill();
  const fw = w * clamp(value) * k;
  if (fw > 1) {
    rr(ctx, x, y - h / 2, fw, h, h / 2);
    const g = ctx.createLinearGradient(x, 0, x + fw, 0);
    g.addColorStop(0, rgba(col, 0.55));
    g.addColorStop(1, col);
    ctx.fillStyle = g;
    ctx.fill();
    glow(ctx, x + fw, y, h * 2.2, col, 0.6 * k);
  }
  ctx.restore();
}

// Vertical feature strip: n thin bars whose heights come from a hash.
export function featureStrip(ctx, x, y, w, h, n, k, o = {}) {
  const col = o.color ?? C.cyan;
  const bw = w / n;
  ctx.save();
  ctx.globalAlpha *= o.alpha ?? 1;
  for (let i = 0; i < n; i++) {
    const v = 0.15 + 0.85 * hash(o.seed ?? 1, i);
    const ki = clamp(k * 1.4 - (i / n) * 0.4);
    if (ki <= 0) continue;
    const bh = h * v * ease.outCubic(ki);
    ctx.fillStyle = rgba(col, 0.35 + 0.6 * v);
    ctx.fillRect(x + i * bw + bw * 0.18, y + (h - bh) / 2, bw * 0.64, bh);
  }
  ctx.restore();
}

// Vertical column of small cells (a "vector").
export function vector(ctx, x, y, cell, n, k, o = {}) {
  const col = o.color ?? C.cyan;
  ctx.save();
  ctx.globalAlpha *= o.alpha ?? 1;
  for (let i = 0; i < n; i++) {
    const ki = clamp(k * 1.5 - (i / n) * 0.5);
    if (ki <= 0) continue;
    const v = hash(o.seed ?? 3, i);
    rr(ctx, x - cell / 2, y + i * (cell + 3), cell, cell, 3);
    ctx.fillStyle = rgba(col, (0.15 + 0.75 * v) * ki);
    ctx.fill();
  }
  ctx.restore();
  return n * (cell + 3) - 3;
}

// Simple monster glyph: a lumpy blob with eyes. Original artwork.
export function monster(ctx, x, y, s, o = {}) {
  const col = o.color ?? '#7a5aa8';
  const t = o.t ?? 0;
  ctx.save();
  ctx.globalAlpha *= o.alpha ?? 1;
  ctx.translate(x, y);
  const r = s / 2;
  const sq = 1 + Math.sin(t * 2.2) * 0.03;
  ctx.scale(1 / sq, sq);
  glow(ctx, 0, 0, r * 1.8, col, 0.25);
  ctx.beginPath();
  for (let i = 0; i <= 40; i++) {
    const a = (i / 40) * TAU;
    const wob = 1 + 0.07 * Math.sin(a * 5 + t * 1.5) + 0.04 * Math.sin(a * 3 - t);
    const rr2 = r * wob * (a > 0 && a < Math.PI ? 0.88 : 1);
    ctx.lineTo(Math.cos(a) * rr2, Math.sin(a) * rr2 * 0.86);
  }
  ctx.closePath();
  const g = ctx.createRadialGradient(-r * 0.3, -r * 0.4, r * 0.1, 0, 0, r * 1.1);
  g.addColorStop(0, mix(col, '#ffffff', 0.35));
  g.addColorStop(0.6, col);
  g.addColorStop(1, mix(col, '#000000', 0.6));
  ctx.fillStyle = g;
  ctx.fill();
  ctx.fillStyle = '#ffe9a8';
  for (const ex of [-0.3, 0.3]) {
    ctx.beginPath();
    ctx.ellipse(ex * r, -r * 0.15, r * 0.12, r * 0.16, 0, 0, TAU);
    ctx.fill();
  }
  ctx.fillStyle = '#1a0f22';
  for (const ex of [-0.3, 0.3]) {
    ctx.beginPath();
    ctx.arc(ex * r + r * 0.03, -r * 0.12, r * 0.06, 0, TAU);
    ctx.fill();
  }
  ctx.restore();
}

// The player's emblem: a red helmet-shield badge for the Ironclad. Original artwork.
export function ironclad(ctx, x, y, s, o = {}) {
  const r = s / 2;
  ctx.save();
  ctx.globalAlpha *= o.alpha ?? 1;
  ctx.translate(x, y);
  glow(ctx, 0, 0, r * 1.8, C.red, 0.22);
  ctx.beginPath();
  ctx.moveTo(0, -r);
  ctx.quadraticCurveTo(r * 0.55, -r * 0.7, r * 0.9, -r * 0.75);
  ctx.quadraticCurveTo(r * 0.95, r * 0.4, 0, r);
  ctx.quadraticCurveTo(-r * 0.95, r * 0.4, -r * 0.9, -r * 0.75);
  ctx.quadraticCurveTo(-r * 0.55, -r * 0.7, 0, -r);
  ctx.closePath();
  const g = ctx.createLinearGradient(0, -r, 0, r);
  g.addColorStop(0, '#d94a3e');
  g.addColorStop(1, '#5e1414');
  ctx.fillStyle = g;
  ctx.fill();
  ctx.lineWidth = r * 0.07;
  ctx.strokeStyle = '#f0c98a';
  ctx.stroke();
  // visor
  ctx.fillStyle = '#1b0d0d';
  ctx.beginPath();
  ctx.moveTo(-r * 0.5, -r * 0.18);
  ctx.lineTo(r * 0.5, -r * 0.18);
  ctx.lineTo(r * 0.38, r * 0.0);
  ctx.lineTo(-r * 0.38, r * 0.0);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = '#f0c98a';
  ctx.lineWidth = r * 0.05;
  ctx.beginPath();
  ctx.moveTo(0, r * 0.1);
  ctx.lineTo(0, r * 0.7);
  ctx.stroke();
  ctx.restore();
}

// Small tag with icon and text, used for "state" readouts.
export function stat(ctx, x, y, iconFn, label, value, o = {}) {
  const col = o.color ?? C.ink;
  ctx.save();
  ctx.globalAlpha *= o.alpha ?? 1;
  iconFn(ctx, x + 14, y - 8, 26, o.iconColor ?? col);
  text(ctx, label, x + 40, y, { size: 20, color: C.sub });
  text(ctx, value, x + (o.valueX ?? 120), y, { size: 22, weight: 700, color: col, fam: o.fam ?? 'sans' });
  ctx.restore();
}

// The teacher's emblem: a gold hexagon with a rotating tick ring.
export function teacherCrest(ctx, x, y, r, k, t) {
  if (k <= 0) return;
  const pulse = 1 + 0.02 * Math.sin(t * 3);
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(ease.outBack(k) * pulse, ease.outBack(k) * pulse);
  glow(ctx, 0, 0, r * 2.4, C.gold, 0.35);
  // rotating outer ring of ticks
  ctx.save();
  ctx.rotate(t * 0.25);
  ctx.strokeStyle = rgba(C.gold, 0.45);
  ctx.lineWidth = 2;
  for (let i = 0; i < 36; i++) {
    const a = (i / 36) * TAU;
    const r0 = r * 1.18, r1 = r * (i % 3 ? 1.24 : 1.32);
    ctx.beginPath();
    ctx.moveTo(Math.cos(a) * r0, Math.sin(a) * r0);
    ctx.lineTo(Math.cos(a) * r1, Math.sin(a) * r1);
    ctx.stroke();
  }
  ctx.restore();
  // hexagon
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const a = Math.PI / 6 + (i * TAU) / 6;
    ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r);
  }
  ctx.closePath();
  const g = ctx.createLinearGradient(0, -r, 0, r);
  g.addColorStop(0, '#4a3714');
  g.addColorStop(1, '#1d1508');
  ctx.fillStyle = g;
  ctx.fill();
  ctx.lineWidth = 4;
  ctx.strokeStyle = C.gold;
  ctx.stroke();
  text(ctx, '老师', 0, 16, { size: 50, weight: 900, fam: 'serif', align: 'center', color: '#ffe3a3' });
  text(ctx, 'P300', 0, 50, { size: 18, weight: 600, fam: 'mono', align: 'center', color: rgba(C.gold, 0.85), ls: 4 });
  ctx.restore();
}

export function fmt(n, d = 0) {
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}
