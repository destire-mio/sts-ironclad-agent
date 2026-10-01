// Deterministic animation core: every frame is a pure function of time t (seconds).
// Scenes draw onto a 1920x1080 canvas; nothing depends on wall-clock time, so the
// preview player and the frame renderer produce identical pictures.

export const W = 1920;
export const H = 1080;

// Shared palette. Colour roles stay fixed across all segments:
// red = combat / search, cyan = network / student, gold = teacher / highlights,
// violet = randomness, green = win / correct.
export const C = {
  bg0: '#06070d',
  bg1: '#100f22',
  ink: '#f5efe4',
  sub: '#b3aec6',
  dim: '#77738f',
  faint: '#4a4762',
  line: 'rgba(255,255,255,0.10)',
  panel: 'rgba(22,21,40,0.72)',
  red: '#ff5b52',
  redDeep: '#b8302d',
  gold: '#f4c561',
  goldDeep: '#b8862c',
  cyan: '#45dccb',
  cyanDeep: '#1f8f86',
  violet: '#a98dff',
  green: '#6fe39c',
  blue: '#5aa8ff',
  orange: '#ff9b4c',
  attack: '#e2574d',
  skill: '#4d8fe0',
  power: '#d9a53e',
};

// ---------------------------------------------------------------- math

export const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
export const lerp = (a, b, k) => a + (b - a) * k;
export const invLerp = (a, b, x) => clamp((x - a) / (b - a));

export const ease = {
  linear: (x) => x,
  inQuad: (x) => x * x,
  outQuad: (x) => 1 - (1 - x) * (1 - x),
  inOutQuad: (x) => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2),
  inCubic: (x) => x * x * x,
  outCubic: (x) => 1 - Math.pow(1 - x, 3),
  inOutCubic: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
  outQuart: (x) => 1 - Math.pow(1 - x, 4),
  outQuint: (x) => 1 - Math.pow(1 - x, 5),
  inOutSine: (x) => -(Math.cos(Math.PI * x) - 1) / 2,
  outExpo: (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)),
  inOutExpo: (x) =>
    x <= 0 ? 0 : x >= 1 ? 1 : x < 0.5 ? Math.pow(2, 20 * x - 10) / 2 : (2 - Math.pow(2, -20 * x + 10)) / 2,
  outBack: (x) => {
    const c1 = 1.70158, c3 = c1 + 1;
    return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2);
  },
  outBackSoft: (x) => {
    const c1 = 0.9, c3 = c1 + 1;
    return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2);
  },
  outElastic: (x) =>
    x <= 0 ? 0 : x >= 1 ? 1 : Math.pow(2, -10 * x) * Math.sin((x * 10 - 0.75) * ((2 * Math.PI) / 3)) + 1,
};

// Progress of a tween that starts at `start` and lasts `dur` seconds.
export function p(t, start, dur, e = ease.outCubic) {
  if (dur <= 0) return t >= start ? 1 : 0;
  return e(clamp((t - start) / dur));
}

// Visibility window: fades in at `a`, fades out at `b`.
export function win(t, a, b, fin = 0.4, fout = 0.4, e = ease.inOutQuad) {
  return Math.min(p(t, a, fin, e), 1 - p(t, b, fout, e));
}

// Deterministic pseudo-random in [0, 1) from any number of integer-ish inputs.
export function hash(...xs) {
  let h = 2166136261 >>> 0;
  for (const x of xs) {
    let v = Math.floor(x * 1000) | 0;
    h ^= v;
    h = Math.imul(h, 16777619);
    h ^= h >>> 13;
    h = Math.imul(h, 0x5bd1e995);
    h ^= h >>> 15;
  }
  return (h >>> 0) / 4294967296;
}

export const TAU = Math.PI * 2;

// Cubic bezier helpers. A path is [p0, c0, c1, p1] with {x, y} points.
export function bez(P, k) {
  const [a, b, c, d] = P;
  const u = 1 - k;
  return {
    x: u * u * u * a.x + 3 * u * u * k * b.x + 3 * u * k * k * c.x + k * k * k * d.x,
    y: u * u * u * a.y + 3 * u * u * k * b.y + 3 * u * k * k * c.y + k * k * k * d.y,
  };
}

// Horizontal-ish S curve between two points.
export function sCurve(x0, y0, x1, y1, bend = 0.5) {
  const dx = (x1 - x0) * bend;
  return [{ x: x0, y: y0 }, { x: x0 + dx, y: y0 }, { x: x1 - dx, y: y1 }, { x: x1, y: y1 }];
}

// Vertical-ish S curve.
export function vCurve(x0, y0, x1, y1, bend = 0.5) {
  const dy = (y1 - y0) * bend;
  return [{ x: x0, y: y0 }, { x: x0, y: y0 + dy }, { x: x1, y: y1 - dy }, { x: x1, y: y1 }];
}

// ---------------------------------------------------------------- colour

const hexCache = new Map();
export function hexRGB(hex) {
  let v = hexCache.get(hex);
  if (!v) {
    const h = hex.replace('#', '');
    v = [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    hexCache.set(hex, v);
  }
  return v;
}

export function rgba(hex, a = 1) {
  const [r, g, b] = hexRGB(hex);
  return `rgba(${r},${g},${b},${clamp(a)})`;
}

export function mix(h1, h2, k) {
  const a = hexRGB(h1), b = hexRGB(h2);
  const c = a.map((v, i) => Math.round(lerp(v, b[i], clamp(k))));
  return '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('');
}

// ---------------------------------------------------------------- fonts

const FAMILY = {
  sans: '"Noto Sans SC", sans-serif',
  serif: '"Noto Serif SC", serif',
  mono: '"JetBrains Mono", "Noto Sans SC", monospace',
};

export function font(size, weight = 400, fam = 'sans') {
  return `${weight} ${size}px ${FAMILY[fam]}`;
}

// Every string drawn is logged per font so the renderer can make sure the
// right (unicode-range split) font files are loaded before a frame is kept.
const seen = new Map();
let dirty = false;

function track(f, s) {
  let set = seen.get(f);
  if (!set) {
    set = new Set();
    seen.set(f, set);
  }
  for (const ch of s) {
    if (!set.has(ch)) {
      set.add(ch);
      dirty = true;
    }
  }
}

export async function ensureFonts() {
  if (!dirty || typeof document === 'undefined') return false;
  dirty = false;
  const jobs = [];
  for (const [f, set] of seen) jobs.push(document.fonts.load(f, [...set].join('')));
  await Promise.all(jobs);
  return true;
}

// Draw text. Options: size, weight, fam, color, align, base, alpha, ls (letter spacing px).
export function text(ctx, s, x, y, o = {}) {
  s = String(s);
  const f = font(o.size ?? 28, o.weight ?? 400, o.fam ?? 'sans');
  track(f, s);
  const a = o.alpha ?? 1;
  if (a <= 0.002) return;
  ctx.save();
  ctx.font = f;
  ctx.fillStyle = o.color ?? C.ink;
  ctx.textAlign = o.align ?? 'left';
  ctx.textBaseline = o.base ?? 'alphabetic';
  ctx.globalAlpha *= a;
  if (o.ls) ctx.letterSpacing = `${o.ls}px`;
  if (o.shadow) {
    ctx.shadowColor = o.shadow;
    ctx.shadowBlur = o.shadowBlur ?? 18;
  }
  if (o.stroke) {
    ctx.lineWidth = o.strokeWidth ?? 4;
    ctx.strokeStyle = o.stroke;
    ctx.lineJoin = 'round';
    ctx.strokeText(s, x, y);
  }
  ctx.fillText(s, x, y);
  ctx.restore();
}

export function measure(ctx, s, size, weight = 400, fam = 'sans', ls = 0) {
  s = String(s);
  const f = font(size, weight, fam);
  track(f, s);
  ctx.save();
  ctx.font = f;
  if (ls) ctx.letterSpacing = `${ls}px`;
  const w = ctx.measureText(s).width;
  ctx.restore();
  return w;
}

// Text revealed character by character (each char rises and fades in).
export function textReveal(ctx, s, x, y, k, o = {}) {
  s = String(s);
  const chars = [...s];
  const size = o.size ?? 28;
  const spread = o.spread ?? 0.55; // fraction of the timeline used for staggering
  const rise = o.rise ?? size * 0.35;
  const total = measure(ctx, s, size, o.weight, o.fam, o.ls);
  let cx = o.align === 'center' ? x - total / 2 : o.align === 'right' ? x - total : x;
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    const w = measure(ctx, ch, size, o.weight, o.fam) + (o.ls ?? 0);
    const start = chars.length > 1 ? (i / (chars.length - 1)) * spread : 0;
    const local = ease.outCubic(clamp((k - start) / (1 - spread)));
    text(ctx, ch, cx, y + (1 - local) * rise, { ...o, align: 'left', alpha: (o.alpha ?? 1) * local, ls: 0 });
    cx += w;
  }
  return total;
}

// Digits that flicker before locking in from left to right (for numbers/RNG).
export function scramble(s, k, seed = 0, t = 0) {
  const chars = [...String(s)];
  const n = chars.length;
  return chars
    .map((ch, i) => {
      const lock = (i + 1) / n;
      if (k >= lock || !/[0-9a-f]/i.test(ch)) return ch;
      const r = hash(seed, i, Math.floor(t * 24));
      return /[0-9]/.test(ch) ? String(Math.floor(r * 10)) : 'abcdef'[Math.floor(r * 6)];
    })
    .join('');
}

// ---------------------------------------------------------------- glow sprites

const glowCache = new Map();
function glowSprite(color) {
  let c = glowCache.get(color);
  if (c) return c;
  c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  gr.addColorStop(0, rgba(color, 1));
  gr.addColorStop(0.18, rgba(color, 0.55));
  gr.addColorStop(0.45, rgba(color, 0.16));
  gr.addColorStop(1, rgba(color, 0));
  g.fillStyle = gr;
  g.fillRect(0, 0, 128, 128);
  glowCache.set(color, c);
  return c;
}

// Additive soft glow centred at (x, y) with radius r.
export function glow(ctx, x, y, r, color, a = 1, sx = 1, sy = 1) {
  if (a <= 0.002 || r <= 0) return;
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  ctx.globalAlpha *= clamp(a);
  ctx.drawImage(glowSprite(color), x - r * sx, y - r * sy, 2 * r * sx, 2 * r * sy);
  ctx.restore();
}

// ---------------------------------------------------------------- background

let bgCanvas = null;
function buildBackground() {
  const c = document.createElement('canvas');
  c.width = W;
  c.height = H;
  const g = c.getContext('2d');
  const lin = g.createLinearGradient(0, 0, 0, H);
  lin.addColorStop(0, '#0d0c1c');
  lin.addColorStop(0.55, '#09091a');
  lin.addColorStop(1, '#060610');
  g.fillStyle = lin;
  g.fillRect(0, 0, W, H);
  const top = g.createRadialGradient(W * 0.5, -H * 0.15, 0, W * 0.5, -H * 0.15, H * 1.05);
  top.addColorStop(0, 'rgba(70,52,130,0.42)');
  top.addColorStop(0.5, 'rgba(45,32,90,0.14)');
  top.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = top;
  g.fillRect(0, 0, W, H);
  const warm = g.createRadialGradient(W * 0.5, H * 1.25, 0, W * 0.5, H * 1.25, H * 0.95);
  warm.addColorStop(0, 'rgba(150,50,35,0.30)');
  warm.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = warm;
  g.fillRect(0, 0, W, H);
  const vig = g.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, H * 1.02);
  vig.addColorStop(0, 'rgba(0,0,0,0)');
  vig.addColorStop(1, 'rgba(0,0,0,0.62)');
  g.fillStyle = vig;
  g.fillRect(0, 0, W, H);
  // Static grain to break up gradient banding after 8-bit encoding.
  const img = g.getImageData(0, 0, W, H);
  const d = img.data;
  let s = 1234567;
  for (let i = 0; i < d.length; i += 4) {
    s = (Math.imul(s, 1103515245) + 12345) >>> 0;
    const n = ((s >>> 16) & 7) - 3.5;
    d[i] += n;
    d[i + 1] += n;
    d[i + 2] += n;
  }
  g.putImageData(img, 0, 0);
  // Very faint diagonal hatch for texture.
  g.globalAlpha = 0.025;
  g.strokeStyle = '#ffffff';
  g.lineWidth = 1;
  for (let x = -H; x < W; x += 6) {
    g.beginPath();
    g.moveTo(x, H);
    g.lineTo(x + H, 0);
    g.stroke();
  }
  return c;
}

const EMBERS = Array.from({ length: 44 }, (_, i) => ({
  x: hash(i, 1) * W,
  speed: 26 + hash(i, 2) * 48,
  off: hash(i, 3),
  size: 1 + hash(i, 4) * 2.2,
  sway: 12 + hash(i, 5) * 30,
  freq: 0.25 + hash(i, 6) * 0.5,
  hue: hash(i, 7),
}));

export function drawBackground(ctx, t, o = {}) {
  if (!bgCanvas) bgCanvas = buildBackground();
  ctx.drawImage(bgCanvas, 0, 0);
  // Drifting colour clouds.
  const clouds = o.clouds ?? [
    [0.18, 0.3, C.violet, 0.10],
    [0.82, 0.72, C.red, 0.07],
    [0.6, 0.18, C.blue, 0.06],
  ];
  clouds.forEach(([cx, cy, col, a], i) => {
    const x = W * cx + Math.sin(t * 0.07 + i * 2.1) * 90;
    const y = H * cy + Math.cos(t * 0.06 + i * 1.3) * 60;
    glow(ctx, x, y, 620, col, a);
  });
  // Rising embers.
  const ea = o.embers ?? 1;
  if (ea > 0) {
    for (let i = 0; i < EMBERS.length; i++) {
      const e = EMBERS[i];
      const span = H + 120;
      const y = H + 60 - ((t * e.speed + e.off * span) % span);
      const x = e.x + Math.sin(t * e.freq + i) * e.sway;
      const life = clamp((H + 60 - y) / 200) * clamp(y / 380);
      const flick = 0.55 + 0.45 * Math.sin(t * (2 + e.hue * 3) + i * 1.7);
      const col = e.hue > 0.75 ? C.gold : C.orange;
      const a = 0.55 * life * flick * ea;
      glow(ctx, x, y, e.size * 7, col, a * 0.7);
      ctx.save();
      ctx.globalAlpha *= a;
      ctx.fillStyle = '#ffe2b8';
      ctx.beginPath();
      ctx.arc(x, y, e.size * 0.6, 0, TAU);
      ctx.fill();
      ctx.restore();
    }
  }
}

// ---------------------------------------------------------------- chapter title

// Shared segment opening: the title appears large in the centre, then glides to
// the top-left corner and stays there as the segment header.
export function chapter(ctx, t, o) {
  const { num, title, sub } = o;
  const hold = o.hold ?? 1.25;
  const move = 0.85;
  const big = 84, small = 46;
  const kIn = p(t, 0.05, 0.9, ease.outCubic);
  const kMove = p(t, hold, move, ease.inOutCubic);
  const w = measure(ctx, title, big, 900, 'serif', 4);
  const scale = lerp(1, small / big, kMove);
  const x = lerp(W / 2 - w / 2, 120, kMove);
  const y = lerp(H / 2 + 34, 132, kMove);

  // Number tag above the title.
  const tagY = y - lerp(96, 62, kMove);
  const tagA = p(t, 0, 0.6);
  text(ctx, `PART ${num}`, x, tagY, {
    size: lerp(24, 20, kMove), weight: 600, fam: 'mono', color: C.gold, alpha: tagA, ls: 6,
  });

  ctx.save();
  ctx.translate(x, y);
  ctx.scale(scale, scale);
  textReveal(ctx, title, 0, 0, kIn, { size: big, weight: 900, fam: 'serif', color: C.ink, ls: 4, spread: 0.5 });
  ctx.restore();

  // Gold rule under the title.
  const ruleK = p(t, 0.35, 0.9, ease.outExpo);
  const ruleW = lerp(w, 120 / scale, kMove) * scale;
  const ruleY = y + lerp(34, 22, kMove);
  ctx.save();
  const gr = ctx.createLinearGradient(x, 0, x + ruleW, 0);
  gr.addColorStop(0, rgba(C.gold, 0.95));
  gr.addColorStop(1, rgba(C.gold, 0));
  ctx.fillStyle = gr;
  ctx.fillRect(x, ruleY, ruleW * ruleK, 3);
  ctx.restore();

  if (sub) {
    const sa = p(t, hold + move * 0.6, 0.6);
    text(ctx, sub, 120 + (1 - sa) * -14, 196, { size: 26, color: C.sub, alpha: sa });
  }
  return kMove;
}

// ---------------------------------------------------------------- shapes

export function rr(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

// Glass panel.
export function panel(ctx, x, y, w, h, o = {}) {
  const a = o.alpha ?? 1;
  if (a <= 0.002) return;
  const r = o.r ?? 20;
  const col = o.color ?? '#ffffff';
  ctx.save();
  ctx.globalAlpha *= a;
  if (o.glow) glow(ctx, x + w / 2, y + h / 2, Math.max(w, h) * 0.75, o.glow, o.glowA ?? 0.18, 1, h / Math.max(w, h));
  rr(ctx, x, y, w, h, r);
  const g = ctx.createLinearGradient(0, y, 0, y + h);
  g.addColorStop(0, o.fillTop ?? 'rgba(34,32,60,0.82)');
  g.addColorStop(1, o.fillBottom ?? 'rgba(16,15,30,0.82)');
  ctx.fillStyle = g;
  ctx.fill();
  ctx.lineWidth = o.lw ?? 1.5;
  ctx.strokeStyle = o.stroke ?? rgba(col, 0.13);
  ctx.stroke();
  // top highlight
  ctx.save();
  rr(ctx, x, y, w, h, r);
  ctx.clip();
  const hg = ctx.createLinearGradient(0, y, 0, y + 60);
  hg.addColorStop(0, 'rgba(255,255,255,0.06)');
  hg.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = hg;
  ctx.fillRect(x, y, w, 60);
  ctx.restore();
  if (o.accent) {
    ctx.fillStyle = o.accent;
    rr(ctx, x + 22, y, Math.min(90, w - 44), 3, 2);
    ctx.fill();
  }
  ctx.restore();
}

// Pill-shaped label. Returns its width.
export function chip(ctx, x, y, label, o = {}) {
  const size = o.size ?? 22;
  const padX = o.padX ?? size * 0.75;
  const h = o.h ?? size * 1.75;
  const iconW = o.icon ? size * 1.15 : 0;
  const tw = measure(ctx, label, size, o.weight ?? 500, o.fam ?? 'sans');
  const w = tw + padX * 2 + iconW;
  const a = o.alpha ?? 1;
  if (a <= 0.002) return w;
  const col = o.color ?? C.sub;
  let x0 = o.align === 'center' ? x - w / 2 : o.align === 'right' ? x - w : x;
  ctx.save();
  ctx.globalAlpha *= a;
  rr(ctx, x0, y - h / 2, w, h, h / 2);
  ctx.fillStyle = o.fill ?? rgba(col, 0.12);
  ctx.fill();
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = o.stroke ?? rgba(col, 0.55);
  ctx.stroke();
  if (o.icon) o.icon(ctx, x0 + padX + size * 0.45, y, size * 0.95, o.iconColor ?? col);
  text(ctx, label, x0 + padX + iconW, y + size * 0.36, {
    size, weight: o.weight ?? 500, fam: o.fam ?? 'sans', color: o.textColor ?? C.ink,
  });
  ctx.restore();
  return w;
}

// Polyline sampled along a bezier, drawn from k0 to k1 of its length.
export function strokeBez(ctx, P, k0, k1, o = {}) {
  if (k1 <= k0) return;
  const n = o.steps ?? 48;
  ctx.save();
  ctx.globalAlpha *= o.alpha ?? 1;
  ctx.strokeStyle = o.color ?? C.sub;
  ctx.lineWidth = o.width ?? 2;
  ctx.lineCap = 'round';
  if (o.dash) {
    ctx.setLineDash(o.dash);
    ctx.lineDashOffset = o.dashOffset ?? 0;
  }
  ctx.beginPath();
  for (let i = 0; i <= n; i++) {
    const k = lerp(k0, k1, i / n);
    const q = bez(P, k);
    if (i === 0) ctx.moveTo(q.x, q.y);
    else ctx.lineTo(q.x, q.y);
  }
  ctx.stroke();
  ctx.restore();
}

// A connector that draws itself in (k) and carries moving light dots.
export function flow(ctx, P, k, t, o = {}) {
  const col = o.color ?? C.sub;
  const a = o.alpha ?? 1;
  if (a <= 0.002 || k <= 0) return;
  strokeBez(ctx, P, 0, k, { color: rgba(col, 0.32 * a), width: o.width ?? 2 });
  if (o.dots !== 0 && k > 0.02) {
    const n = o.dots ?? 3;
    const speed = o.speed ?? 0.6;
    for (let i = 0; i < n; i++) {
      const ph = (t * speed + i / n) % 1;
      if (ph > k) continue;
      const q = bez(P, ph);
      const fade = Math.sin(Math.PI * ph);
      glow(ctx, q.x, q.y, o.dotGlow ?? 16, col, 0.8 * a * fade);
      ctx.save();
      ctx.globalAlpha *= a * fade;
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(q.x, q.y, o.dotR ?? 2.6, 0, TAU);
      ctx.fill();
      ctx.restore();
    }
  }
  if (o.arrow && k > 0.98) {
    const q1 = bez(P, 1), q0 = bez(P, 0.97);
    arrowHead(ctx, q1.x, q1.y, Math.atan2(q1.y - q0.y, q1.x - q0.x), o.arrowSize ?? 12, rgba(col, 0.8 * a));
  }
}

export function arrowHead(ctx, x, y, ang, s, color) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(ang);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(-s, -s * 0.55);
  ctx.lineTo(-s * 0.7, 0);
  ctx.lineTo(-s, s * 0.55);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

// Expanding ring burst.
export function ring(ctx, x, y, k, o = {}) {
  if (k <= 0 || k >= 1) return;
  const r = lerp(o.r0 ?? 10, o.r1 ?? 90, ease.outCubic(k));
  ctx.save();
  ctx.globalAlpha *= (1 - k) * (o.alpha ?? 1);
  ctx.strokeStyle = o.color ?? C.gold;
  ctx.lineWidth = o.width ?? 3;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, TAU);
  ctx.stroke();
  ctx.restore();
}

// Run a draw function inside a transformed / faded context.
export function group(ctx, o, fn) {
  const a = o.alpha ?? 1;
  if (a <= 0.002) return;
  ctx.save();
  ctx.globalAlpha *= a;
  if (o.x || o.y) ctx.translate(o.x ?? 0, o.y ?? 0);
  if (o.rot) ctx.rotate(o.rot);
  if (o.scale !== undefined && o.scale !== 1) ctx.scale(o.scale, o.scale);
  fn(ctx);
  ctx.restore();
}

// ---------------------------------------------------------------- scene frame

let layer = null;
export function renderScene(ctx, scene, t) {
  if (!layer) {
    layer = document.createElement('canvas');
    layer.width = W;
    layer.height = H;
  }
  const D = scene.duration;
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = 'source-over';
  drawBackground(ctx, t, scene.background);
  const lc = layer.getContext('2d');
  lc.setTransform(1, 0, 0, 1, 0, 0);
  lc.globalAlpha = 1;
  lc.clearRect(0, 0, W, H);
  scene.draw(lc, t);
  const out = 1 - p(t, D - 0.75, 0.75, ease.inOutQuad);
  const inn = p(t, 0, 0.3, ease.outQuad);
  ctx.globalAlpha = out * inn;
  ctx.drawImage(layer, 0, 0);
  ctx.restore();
}
