// Hand-drawn vector icons. Each takes (ctx, x, y, size, color, opts) and is
// centred on (x, y). All artwork is original; no game assets are used.
import { C, TAU, rgba, text, glow } from './engine.js';

function stroke(ctx, s, color, w = 0.085) {
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = Math.max(1.2, s * w);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
}

function wrap(ctx, x, y, s, fn) {
  ctx.save();
  ctx.translate(x, y);
  fn(s / 2);
  ctx.restore();
}

export function sword(ctx, x, y, s, color = C.ink, o = {}) {
  wrap(ctx, x, y, s, (r) => {
    ctx.rotate(o.rot ?? -Math.PI / 4);
    stroke(ctx, s, color);
    ctx.beginPath();
    ctx.moveTo(0, r * 0.95);
    ctx.lineTo(0, -r * 0.55);
    ctx.stroke();
    ctx.beginPath(); // blade
    ctx.moveTo(-r * 0.13, r * 0.35);
    ctx.lineTo(-r * 0.13, -r * 0.7);
    ctx.lineTo(0, -r * 0.98);
    ctx.lineTo(r * 0.13, -r * 0.7);
    ctx.lineTo(r * 0.13, r * 0.35);
    ctx.closePath();
    ctx.globalAlpha *= 0.35;
    ctx.fill();
    ctx.globalAlpha /= 0.35;
    ctx.stroke();
    ctx.beginPath(); // guard
    ctx.moveTo(-r * 0.42, r * 0.38);
    ctx.lineTo(r * 0.42, r * 0.38);
    ctx.stroke();
  });
}

export function swords(ctx, x, y, s, color = C.ink) {
  sword(ctx, x, y, s, color, { rot: -Math.PI / 4 });
  sword(ctx, x, y, s, color, { rot: Math.PI / 4 });
}

export function shield(ctx, x, y, s, color = C.ink, o = {}) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color);
    ctx.beginPath();
    ctx.moveTo(0, -r * 0.92);
    ctx.quadraticCurveTo(r * 0.45, -r * 0.62, r * 0.82, -r * 0.66);
    ctx.quadraticCurveTo(r * 0.86, r * 0.35, 0, r * 0.95);
    ctx.quadraticCurveTo(-r * 0.86, r * 0.35, -r * 0.82, -r * 0.66);
    ctx.quadraticCurveTo(-r * 0.45, -r * 0.62, 0, -r * 0.92);
    ctx.closePath();
    if (o.fill) {
      ctx.globalAlpha *= 0.3;
      ctx.fill();
      ctx.globalAlpha /= 0.3;
    }
    ctx.stroke();
  });
}

export function flame(ctx, x, y, s, color = C.orange, o = {}) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color);
    ctx.beginPath();
    ctx.moveTo(0, r * 0.95);
    ctx.bezierCurveTo(-r * 0.85, r * 0.8, -r * 0.75, -r * 0.1, -r * 0.1, -r * 0.95);
    ctx.bezierCurveTo(-r * 0.05, -r * 0.35, r * 0.35, -r * 0.35, r * 0.3, -r * 0.7);
    ctx.bezierCurveTo(r * 0.95, -r * 0.1, r * 0.85, r * 0.8, 0, r * 0.95);
    ctx.closePath();
    ctx.globalAlpha *= o.fillA ?? 0.35;
    ctx.fill();
    ctx.globalAlpha /= o.fillA ?? 0.35;
    ctx.stroke();
  });
}

export function campfire(ctx, x, y, s, color = C.orange) {
  flame(ctx, x, y - s * 0.12, s * 0.7, color);
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color);
    ctx.beginPath();
    ctx.moveTo(-r * 0.7, r * 0.85);
    ctx.lineTo(r * 0.7, r * 0.45);
    ctx.moveTo(r * 0.7, r * 0.85);
    ctx.lineTo(-r * 0.7, r * 0.45);
    ctx.stroke();
  });
}

export function skull(ctx, x, y, s, color = C.ink, o = {}) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color);
    if (o.horns) {
      ctx.beginPath();
      ctx.moveTo(-r * 0.55, -r * 0.35);
      ctx.quadraticCurveTo(-r * 1.0, -r * 0.6, -r * 0.82, -r * 1.0);
      ctx.moveTo(r * 0.55, -r * 0.35);
      ctx.quadraticCurveTo(r * 1.0, -r * 0.6, r * 0.82, -r * 1.0);
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(0, -r * 0.1, r * 0.62, Math.PI * 0.8, Math.PI * 2.2);
    ctx.lineTo(r * 0.38, r * 0.5);
    ctx.lineTo(r * 0.38, r * 0.78);
    ctx.lineTo(-r * 0.38, r * 0.78);
    ctx.lineTo(-r * 0.38, r * 0.5);
    ctx.closePath();
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(-r * 0.24, -r * 0.05, r * 0.15, 0, TAU);
    ctx.arc(r * 0.24, -r * 0.05, r * 0.15, 0, TAU);
    ctx.fill();
  });
}

export function bag(ctx, x, y, s, color = C.gold) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color);
    ctx.beginPath();
    ctx.moveTo(-r * 0.3, -r * 0.55);
    ctx.bezierCurveTo(-r * 1.0, r * 0.0, -r * 0.9, r * 0.92, 0, r * 0.92);
    ctx.bezierCurveTo(r * 0.9, r * 0.92, r * 1.0, r * 0.0, r * 0.3, -r * 0.55);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(-r * 0.38, -r * 0.55);
    ctx.lineTo(r * 0.38, -r * 0.55);
    ctx.moveTo(-r * 0.3, -r * 0.55);
    ctx.lineTo(-r * 0.45, -r * 0.92);
    ctx.lineTo(r * 0.45, -r * 0.92);
    ctx.lineTo(r * 0.3, -r * 0.55);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, r * 0.3, r * 0.26, 0, TAU);
    ctx.stroke();
  });
}

export function coin(ctx, x, y, s, color = C.gold) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color);
    ctx.beginPath();
    ctx.arc(0, 0, r * 0.82, 0, TAU);
    ctx.globalAlpha *= 0.25;
    ctx.fill();
    ctx.globalAlpha /= 0.25;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, 0, r * 0.45, 0, TAU);
    ctx.stroke();
  });
}

export function question(ctx, x, y, s, color = C.ink) {
  text(ctx, '?', x, y + s * 0.36, { size: s * 1.0, weight: 900, fam: 'serif', color, align: 'center' });
}

export function chest(ctx, x, y, s, color = C.gold) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color);
    ctx.beginPath();
    ctx.roundRect(-r * 0.85, -r * 0.2, r * 1.7, r * 0.95, r * 0.08);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(-r * 0.85, -r * 0.2);
    ctx.quadraticCurveTo(-r * 0.85, -r * 0.85, 0, -r * 0.85);
    ctx.quadraticCurveTo(r * 0.85, -r * 0.85, r * 0.85, -r * 0.2);
    ctx.stroke();
    ctx.beginPath();
    ctx.roundRect(-r * 0.15, -r * 0.3, r * 0.3, r * 0.35, r * 0.05);
    ctx.fill();
  });
}

export function heart(ctx, x, y, s, color = C.red, o = {}) {
  wrap(ctx, x, y, s, (r) => {
    ctx.beginPath();
    ctx.moveTo(0, r * 0.95);
    ctx.bezierCurveTo(-r * 1.25, r * 0.05, -r * 0.9, -r * 0.95, 0, -r * 0.45);
    ctx.bezierCurveTo(r * 0.9, -r * 0.95, r * 1.25, r * 0.05, 0, r * 0.95);
    ctx.closePath();
    if (o.outline) {
      stroke(ctx, s, color);
      ctx.stroke();
      return;
    }
    const g = ctx.createRadialGradient(-r * 0.3, -r * 0.3, r * 0.05, 0, 0, r * 1.1);
    g.addColorStop(0, o.light ?? '#ff9a8a');
    g.addColorStop(0.5, color);
    g.addColorStop(1, o.dark ?? '#5a0f16');
    ctx.fillStyle = g;
    ctx.fill();
    if (o.veins) {
      ctx.strokeStyle = 'rgba(40,0,8,0.55)';
      ctx.lineWidth = Math.max(1, s * 0.03);
      ctx.beginPath();
      ctx.moveTo(-r * 0.15, -r * 0.4);
      ctx.quadraticCurveTo(-r * 0.35, r * 0.1, -r * 0.05, r * 0.55);
      ctx.moveTo(r * 0.35, -r * 0.5);
      ctx.quadraticCurveTo(r * 0.2, -r * 0.05, r * 0.45, r * 0.25);
      ctx.stroke();
    }
  });
}

export function key(ctx, x, y, s, color = C.gold, o = {}) {
  wrap(ctx, x, y, s, (r) => {
    ctx.rotate(o.rot ?? -Math.PI / 4);
    stroke(ctx, s, color, 0.1);
    ctx.beginPath();
    ctx.arc(0, -r * 0.5, r * 0.36, 0, TAU);
    ctx.globalAlpha *= 0.3;
    ctx.fill();
    ctx.globalAlpha /= 0.3;
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, -r * 0.14);
    ctx.lineTo(0, r * 0.95);
    ctx.moveTo(0, r * 0.55);
    ctx.lineTo(r * 0.3, r * 0.55);
    ctx.moveTo(0, r * 0.8);
    ctx.lineTo(r * 0.24, r * 0.8);
    ctx.stroke();
  });
}

export function check(ctx, x, y, s, color = C.green) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.13);
    ctx.beginPath();
    ctx.moveTo(-r * 0.6, 0);
    ctx.lineTo(-r * 0.15, r * 0.45);
    ctx.lineTo(r * 0.65, -r * 0.45);
    ctx.stroke();
  });
}

export function cross(ctx, x, y, s, color = C.red) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.13);
    ctx.beginPath();
    ctx.moveTo(-r * 0.5, -r * 0.5);
    ctx.lineTo(r * 0.5, r * 0.5);
    ctx.moveTo(r * 0.5, -r * 0.5);
    ctx.lineTo(-r * 0.5, r * 0.5);
    ctx.stroke();
  });
}

export function lock(ctx, x, y, s, color = C.ink, o = {}) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.1);
    const open = o.open ?? 0;
    ctx.beginPath();
    ctx.roundRect(-r * 0.7, -r * 0.1, r * 1.4, r * 1.0, r * 0.15);
    ctx.globalAlpha *= 0.25;
    ctx.fill();
    ctx.globalAlpha /= 0.25;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, -r * 0.35 - open * r * 0.35, r * 0.42, Math.PI, 0);
    ctx.lineTo(r * 0.42, -r * 0.1 - open * r * 0.35);
    ctx.moveTo(-r * 0.42, -r * 0.35 - open * r * 0.35);
    ctx.lineTo(-r * 0.42, -r * 0.1 - (open > 0 ? r * 0.6 : 0));
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, r * 0.35, r * 0.12, 0, TAU);
    ctx.fill();
  });
}

export function snowflake(ctx, x, y, s, color = '#bfe9ff') {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.08);
    for (let i = 0; i < 6; i++) {
      ctx.save();
      ctx.rotate((i * TAU) / 6);
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(0, -r * 0.95);
      ctx.moveTo(0, -r * 0.55);
      ctx.lineTo(-r * 0.22, -r * 0.75);
      ctx.moveTo(0, -r * 0.55);
      ctx.lineTo(r * 0.22, -r * 0.75);
      ctx.stroke();
      ctx.restore();
    }
  });
}

export function book(ctx, x, y, s, color = C.gold) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.08);
    ctx.beginPath();
    ctx.moveTo(0, -r * 0.6);
    ctx.quadraticCurveTo(-r * 0.45, -r * 0.85, -r * 0.95, -r * 0.7);
    ctx.lineTo(-r * 0.95, r * 0.7);
    ctx.quadraticCurveTo(-r * 0.45, r * 0.55, 0, r * 0.8);
    ctx.quadraticCurveTo(r * 0.45, r * 0.55, r * 0.95, r * 0.7);
    ctx.lineTo(r * 0.95, -r * 0.7);
    ctx.quadraticCurveTo(r * 0.45, -r * 0.85, 0, -r * 0.6);
    ctx.lineTo(0, r * 0.8);
    ctx.stroke();
  });
}

export function database(ctx, x, y, s, color = C.cyan) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.08);
    const rx = r * 0.75, ry = r * 0.24;
    ctx.beginPath();
    ctx.ellipse(0, -r * 0.6, rx, ry, 0, 0, TAU);
    ctx.stroke();
    for (const yy of [-r * 0.6, -r * 0.05, r * 0.5]) {
      ctx.beginPath();
      ctx.ellipse(0, yy, rx, ry, 0, 0, Math.PI);
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.moveTo(-rx, -r * 0.6);
    ctx.lineTo(-rx, r * 0.5);
    ctx.moveTo(rx, -r * 0.6);
    ctx.lineTo(rx, r * 0.5);
    ctx.stroke();
  });
}

export function dice(ctx, x, y, s, color = C.violet, o = {}) {
  wrap(ctx, x, y, s, (r) => {
    ctx.rotate(o.rot ?? 0.2);
    stroke(ctx, s, color, 0.08);
    ctx.beginPath();
    ctx.roundRect(-r * 0.75, -r * 0.75, r * 1.5, r * 1.5, r * 0.28);
    ctx.globalAlpha *= 0.2;
    ctx.fill();
    ctx.globalAlpha /= 0.2;
    ctx.stroke();
    const pip = (px, py) => {
      ctx.beginPath();
      ctx.arc(px * r, py * r, r * 0.12, 0, TAU);
      ctx.fill();
    };
    const face = o.face ?? 5;
    if (face % 2) pip(0, 0);
    if (face > 1) { pip(-0.38, -0.38); pip(0.38, 0.38); }
    if (face > 3) { pip(0.38, -0.38); pip(-0.38, 0.38); }
    if (face === 6) { pip(-0.38, 0); pip(0.38, 0); }
  });
}

export function monitor(ctx, x, y, s, color = C.ink) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.08);
    ctx.beginPath();
    ctx.roundRect(-r * 0.95, -r * 0.75, r * 1.9, r * 1.25, r * 0.1);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(-r * 0.35, r * 0.9);
    ctx.lineTo(r * 0.35, r * 0.9);
    ctx.moveTo(0, r * 0.5);
    ctx.lineTo(0, r * 0.9);
    ctx.stroke();
  });
}

export function chipIcon(ctx, x, y, s, color = C.cyan) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.08);
    ctx.beginPath();
    ctx.roundRect(-r * 0.55, -r * 0.55, r * 1.1, r * 1.1, r * 0.12);
    ctx.stroke();
    ctx.beginPath();
    ctx.roundRect(-r * 0.25, -r * 0.25, r * 0.5, r * 0.5, r * 0.06);
    ctx.fill();
    for (let i = -1; i <= 1; i++) {
      const d = i * r * 0.3;
      ctx.beginPath();
      ctx.moveTo(d, -r * 0.55); ctx.lineTo(d, -r * 0.85);
      ctx.moveTo(d, r * 0.55); ctx.lineTo(d, r * 0.85);
      ctx.moveTo(-r * 0.55, d); ctx.lineTo(-r * 0.85, d);
      ctx.moveTo(r * 0.55, d); ctx.lineTo(r * 0.85, d);
      ctx.stroke();
    }
  });
}

export function brain(ctx, x, y, s, color = C.cyan) {
  // Tiny network glyph: three columns of dots joined by lines.
  wrap(ctx, x, y, s, (r) => {
    const cols = [[-0.7, [-0.45, 0, 0.45]], [0, [-0.6, -0.2, 0.2, 0.6]], [0.7, [0]]];
    ctx.strokeStyle = rgba(color, 0.55);
    ctx.lineWidth = Math.max(1, s * 0.035);
    for (let c = 0; c < cols.length - 1; c++) {
      for (const a of cols[c][1]) for (const b of cols[c + 1][1]) {
        ctx.beginPath();
        ctx.moveTo(cols[c][0] * r, a * r);
        ctx.lineTo(cols[c + 1][0] * r, b * r);
        ctx.stroke();
      }
    }
    ctx.fillStyle = color;
    for (const [cx, ys] of cols) for (const yy of ys) {
      ctx.beginPath();
      ctx.arc(cx * r, yy * r, r * 0.12, 0, TAU);
      ctx.fill();
    }
  });
}

export function tree(ctx, x, y, s, color = C.red) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.07);
    const pts = [[0, -0.75], [-0.55, 0], [0.55, 0], [-0.8, 0.75], [-0.3, 0.75], [0.3, 0.75], [0.8, 0.75]];
    const edges = [[0, 1], [0, 2], [1, 3], [1, 4], [2, 5], [2, 6]];
    ctx.beginPath();
    for (const [a, b] of edges) {
      ctx.moveTo(pts[a][0] * r, pts[a][1] * r);
      ctx.lineTo(pts[b][0] * r, pts[b][1] * r);
    }
    ctx.stroke();
    for (const [px, py] of pts) {
      ctx.beginPath();
      ctx.arc(px * r, py * r, r * 0.14, 0, TAU);
      ctx.fill();
    }
  });
}

export function crown(ctx, x, y, s, color = C.gold) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.08);
    ctx.beginPath();
    ctx.moveTo(-r * 0.85, r * 0.55);
    ctx.lineTo(-r * 0.9, -r * 0.45);
    ctx.lineTo(-r * 0.4, r * 0.0);
    ctx.lineTo(0, -r * 0.7);
    ctx.lineTo(r * 0.4, r * 0.0);
    ctx.lineTo(r * 0.9, -r * 0.45);
    ctx.lineTo(r * 0.85, r * 0.55);
    ctx.closePath();
    ctx.globalAlpha *= 0.3;
    ctx.fill();
    ctx.globalAlpha /= 0.3;
    ctx.stroke();
  });
}

export function hourglass(ctx, x, y, s, color = C.gold) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.08);
    ctx.beginPath();
    ctx.moveTo(-r * 0.6, -r * 0.85); ctx.lineTo(r * 0.6, -r * 0.85);
    ctx.moveTo(-r * 0.6, r * 0.85); ctx.lineTo(r * 0.6, r * 0.85);
    ctx.moveTo(-r * 0.45, -r * 0.85);
    ctx.quadraticCurveTo(-r * 0.45, -r * 0.2, 0, 0);
    ctx.quadraticCurveTo(-r * 0.45, r * 0.2, -r * 0.45, r * 0.85);
    ctx.moveTo(r * 0.45, -r * 0.85);
    ctx.quadraticCurveTo(r * 0.45, -r * 0.2, 0, 0);
    ctx.quadraticCurveTo(r * 0.45, r * 0.2, r * 0.45, r * 0.85);
    ctx.stroke();
  });
}

export function loop(ctx, x, y, s, color = C.cyan) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.09);
    ctx.beginPath();
    ctx.arc(0, 0, r * 0.65, -Math.PI * 0.15, Math.PI * 1.35);
    ctx.stroke();
    const a = -Math.PI * 0.15;
    const px = Math.cos(a) * r * 0.65, py = Math.sin(a) * r * 0.65;
    ctx.beginPath();
    ctx.moveTo(px + r * 0.28, py - r * 0.05);
    ctx.lineTo(px, py);
    ctx.lineTo(px - r * 0.02, py - r * 0.3);
    ctx.stroke();
  });
}

export function eye(ctx, x, y, s, color = C.ink) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.08);
    ctx.beginPath();
    ctx.moveTo(-r * 0.95, 0);
    ctx.quadraticCurveTo(0, -r * 0.85, r * 0.95, 0);
    ctx.quadraticCurveTo(0, r * 0.85, -r * 0.95, 0);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, 0, r * 0.25, 0, TAU);
    ctx.fill();
  });
}

export function fork(ctx, x, y, s, color = C.gold) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.09);
    ctx.beginPath();
    ctx.moveTo(-r * 0.4, r * 0.85);
    ctx.lineTo(-r * 0.4, -r * 0.55);
    ctx.moveTo(-r * 0.4, r * 0.3);
    ctx.bezierCurveTo(-r * 0.4, -r * 0.05, r * 0.4, 0, r * 0.4, -r * 0.55);
    ctx.stroke();
    for (const [px, py] of [[-0.4, -0.7], [0.4, -0.7], [-0.4, 0.85]]) {
      ctx.beginPath();
      ctx.arc(px * r, py * r, r * 0.16, 0, TAU);
      ctx.fill();
    }
  });
}

export function repo(ctx, x, y, s, color = C.ink) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.08);
    ctx.beginPath();
    ctx.moveTo(-r * 0.7, r * 0.6);
    ctx.lineTo(-r * 0.7, -r * 0.7);
    ctx.quadraticCurveTo(-r * 0.7, -r * 0.9, -r * 0.5, -r * 0.9);
    ctx.lineTo(r * 0.7, -r * 0.9);
    ctx.lineTo(r * 0.7, r * 0.5);
    ctx.lineTo(-r * 0.5, r * 0.5);
    ctx.quadraticCurveTo(-r * 0.7, r * 0.5, -r * 0.7, r * 0.7);
    ctx.quadraticCurveTo(-r * 0.7, r * 0.9, -r * 0.5, r * 0.9);
    ctx.lineTo(-r * 0.2, r * 0.9);
    ctx.stroke();
  });
}

export function star(ctx, x, y, s, color = C.gold) {
  wrap(ctx, x, y, s, (r) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    for (let i = 0; i < 10; i++) {
      const a = -Math.PI / 2 + (i * Math.PI) / 5;
      const rr = i % 2 ? r * 0.42 : r;
      ctx.lineTo(Math.cos(a) * rr, Math.sin(a) * rr);
    }
    ctx.closePath();
    ctx.fill();
  });
}

export function bolt(ctx, x, y, s, color = C.gold) {
  wrap(ctx, x, y, s, (r) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(r * 0.15, -r * 0.95);
    ctx.lineTo(-r * 0.55, r * 0.1);
    ctx.lineTo(-r * 0.05, r * 0.1);
    ctx.lineTo(-r * 0.2, r * 0.95);
    ctx.lineTo(r * 0.55, -r * 0.15);
    ctx.lineTo(r * 0.05, -r * 0.15);
    ctx.closePath();
    ctx.fill();
  });
}

export function doc(ctx, x, y, s, color = C.ink) {
  wrap(ctx, x, y, s, (r) => {
    stroke(ctx, s, color, 0.08);
    ctx.beginPath();
    ctx.moveTo(-r * 0.6, -r * 0.9);
    ctx.lineTo(r * 0.25, -r * 0.9);
    ctx.lineTo(r * 0.6, -r * 0.55);
    ctx.lineTo(r * 0.6, r * 0.9);
    ctx.lineTo(-r * 0.6, r * 0.9);
    ctx.closePath();
    ctx.stroke();
    ctx.beginPath();
    for (const yy of [-0.2, 0.15, 0.5]) {
      ctx.moveTo(-r * 0.35, yy * r);
      ctx.lineTo(r * 0.35, yy * r);
    }
    ctx.stroke();
  });
}

// Map node: circle with an icon. kind: fight, elite, rest, shop, event, chest, boss, heart, start.
export function mapNode(ctx, x, y, r, kind, o = {}) {
  const a = o.alpha ?? 1;
  if (a <= 0.002) return;
  const col = o.color ?? NODE_COLOR[kind] ?? C.ink;
  ctx.save();
  ctx.globalAlpha *= a;
  if (o.active) glow(ctx, x, y, r * 3, col, 0.5 * o.active);
  ctx.beginPath();
  ctx.arc(x, y, r, 0, TAU);
  const g = ctx.createRadialGradient(x, y - r * 0.5, r * 0.1, x, y, r);
  g.addColorStop(0, '#2a2742');
  g.addColorStop(1, '#14131f');
  ctx.fillStyle = g;
  ctx.fill();
  ctx.lineWidth = Math.max(1.5, r * 0.08);
  ctx.strokeStyle = rgba(col, o.active ? 0.6 + 0.4 * o.active : 0.55);
  ctx.stroke();
  const s = r * 1.15;
  const ic = o.iconColor ?? col;
  switch (kind) {
    case 'fight': swords(ctx, x, y, s * 0.9, ic); break;
    case 'elite': skull(ctx, x, y + r * 0.08, s * 0.95, ic, { horns: true }); break;
    case 'rest': campfire(ctx, x, y, s, ic); break;
    case 'shop': bag(ctx, x, y, s * 0.9, ic); break;
    case 'event': question(ctx, x, y, s * 0.95, ic); break;
    case 'chest': chest(ctx, x, y, s * 0.9, ic); break;
    case 'boss': skull(ctx, x, y + r * 0.1, s * 1.05, ic, { horns: true }); break;
    case 'heart': heart(ctx, x, y, s * 1.1, C.red, { veins: true }); break;
    case 'start': star(ctx, x, y, s * 0.8, ic); break;
    default: break;
  }
  ctx.restore();
}

export const NODE_COLOR = {
  fight: '#e8dcc8',
  elite: C.orange,
  rest: C.orange,
  shop: C.gold,
  event: C.violet,
  chest: C.gold,
  boss: C.red,
  heart: C.red,
  start: C.gold,
};

export const NODE_LABEL = {
  fight: '战斗',
  elite: '精英',
  rest: '篝火',
  shop: '商店',
  event: '事件',
  chest: '宝箱',
  boss: 'Boss',
  heart: '心脏',
  start: '涅奥',
};
