// 12 片尾: repository card with QR code, related repositories and credits.
import { C, p, ease, clamp, lerp, rgba, text, glow, panel, chapter, chip, measure, textReveal } from '../engine.js';
import * as I from '../icons.js';
import { REPO } from '../config.js';
import { QR } from '../qr.js';

const CARD = { x: 150, y: 290, w: 1060, h: 430 };
const QRP = { x: 1300, y: 290, w: 470, h: 430 };

export default {
  id: 's12',
  num: '12',
  file: '12-outro',
  title: '代码已开源',
  duration: 12,
  draw(ctx, t) {
    chapter(ctx, t, { num: '12', title: '代码已开源', sub: '引擎源码、冻结网络、价值表和评测记录都在仓库里' });

    // ---- repo card
    const ca = p(t, 2.0, 0.8, ease.outCubic);
    panel(ctx, CARD.x, CARD.y + (1 - ca) * 30, CARD.w, CARD.h, { alpha: ca, accent: C.gold, glow: C.gold, glowA: 0.06 });
    ctx.save();
    ctx.globalAlpha *= ca;
    const x0 = CARD.x + 50;
    I.repo(ctx, x0 + 18, CARD.y + 74, 40, C.sub);
    text(ctx, `${REPO.owner} /`, x0 + 56, CARD.y + 86, { size: 30, fam: 'mono', color: C.sub });
    const ow = measure(ctx, `${REPO.owner} /`, 30, 400, 'mono');
    text(ctx, REPO.name, x0 + 56 + ow + 14, CARD.y + 86, { size: 34, weight: 700, fam: 'mono', color: C.ink });
    ctx.restore();
    textReveal(ctx, '杀戮尖塔 A20 铁甲战士 AI', x0, CARD.y + 178, p(t, 2.5, 1.0), { size: 52, weight: 900, fam: 'serif', color: '#f6cf74', spread: 0.5 });
    text(ctx, '局外选择：一个冻结的神经网络  ·  战斗出牌：模拟器搜索  ·  真实游戏验证', x0, CARD.y + 236, { size: 23, color: C.sub, alpha: p(t, 3.1, 0.6) });
    let cx = x0;
    ['Python', 'C++', 'PyTorch', `${REPO.license} 开源`].forEach((s, i) => {
      const k = p(t, 3.4 + i * 0.12, 0.5, ease.outBack);
      cx += chip(ctx, cx, CARD.y + 296, s, { color: i === 3 ? C.green : C.sub, size: 19, alpha: clamp(k) }) + 10;
    });
    // URL typed in
    const uk = p(t, 3.9, 1.2, ease.linear);
    const url = REPO.url;
    const shown = url.slice(0, Math.round(url.length * uk));
    ctx.save();
    ctx.globalAlpha *= p(t, 3.8, 0.3);
    ctx.beginPath();
    ctx.roundRect(x0 - 6, CARD.y + 340, CARD.w - 88, 60, 12);
    ctx.fillStyle = 'rgba(0,0,0,0.3)';
    ctx.fill();
    ctx.strokeStyle = rgba(C.gold, 0.35);
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.restore();
    text(ctx, shown, x0 + 18, CARD.y + 381, { size: 30, weight: 600, fam: 'mono', color: C.gold });
    if (uk < 1 || Math.floor(t * 2) % 2) {
      const cw = measure(ctx, shown, 30, 600, 'mono');
      ctx.save();
      ctx.globalAlpha *= p(t, 3.8, 0.3);
      ctx.fillStyle = C.gold;
      ctx.fillRect(x0 + 22 + cw, CARD.y + 354, 3, 34);
      ctx.restore();
    }

    // ---- QR code
    const qa = p(t, 2.4, 0.8);
    panel(ctx, QRP.x, QRP.y + (1 - qa) * 30, QRP.w, QRP.h, { alpha: qa });
    const n = QR.length;
    const cell = 9;
    const size = n * cell;
    const qx = QRP.x + (QRP.w - size) / 2, qy = QRP.y + 46;
    ctx.save();
    ctx.globalAlpha *= qa;
    ctx.fillStyle = '#f5efe4';
    ctx.beginPath();
    ctx.roundRect(qx - 26, qy - 26, size + 52, size + 52, 14);
    ctx.fill();
    ctx.fillStyle = '#12101e';
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        if (QR[y][x] !== '1') continue;
        const d = (x + y) / (2 * n);
        const k = clamp((t - 2.8 - d * 1.2) / 0.3);
        if (k <= 0) continue;
        const s = cell * ease.outBack(k);
        ctx.fillRect(qx + x * cell + (cell - s) / 2, qy + y * cell + (cell - s) / 2, s + 0.4, s + 0.4);
      }
    }
    // glint sweep
    const gk = (t - 4.4) / 1.0;
    if (gk > 0 && gk < 1) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(qx - 16, qy - 16, size + 32, size + 32);
      ctx.clip();
      const gx = lerp(qx - 120, qx + size + 120, gk);
      const g = ctx.createLinearGradient(gx - 60, 0, gx + 60, 0);
      g.addColorStop(0, 'rgba(255,230,160,0)');
      g.addColorStop(0.5, 'rgba(255,230,160,0.35)');
      g.addColorStop(1, 'rgba(255,230,160,0)');
      ctx.fillStyle = g;
      ctx.fillRect(qx - 16, qy - 16, size + 32, size + 32);
      ctx.restore();
    }
    ctx.restore();
    text(ctx, '扫码打开仓库', QRP.x + QRP.w / 2, QRP.y + QRP.h - 30, { size: 22, weight: 700, align: 'center', alpha: qa });

    // ---- related + credits
    const ra = p(t, 5.0, 0.6);
    text(ctx, '相关仓库', CARD.x, 790, { size: 20, weight: 700, color: C.sub, alpha: ra });
    let rx = CARD.x + 104;
    REPO.related.forEach((r, i) => {
      const k = p(t, 5.1 + i * 0.15, 0.5, ease.outBack);
      rx += chip(ctx, rx, 783, `${r.name} · ${r.note}`, { color: C.cyan, size: 19, alpha: clamp(k), icon: I.repo }) + 12;
    });
    const ka = p(t, 5.6, 0.6);
    text(ctx, '致谢', CARD.x, 846, { size: 20, weight: 700, color: C.sub, alpha: ka });
    text(ctx, 'sts_lightspeed（模拟器） · CommunicationMod · ModTheSpire · BaseMod · 延续自 Jialeiv/sts-rl-agent', CARD.x + 104, 846, { size: 20, color: C.ink, alpha: ka });
    text(ctx, '《杀戮尖塔》（Slay the Spire）是 Mega Crit 的商标；本项目为非官方研究项目，与 Mega Crit 无关联。', CARD.x, 900, { size: 17, color: C.dim, alpha: p(t, 6.0, 0.6) });

    // ---- ambient heart and keys, top right
    const ha = p(t, 2.0, 1.0);
    const hx = 1700, hy = 150;
    const beat = 1 + 0.05 * Math.exp(-Math.pow(((t % 1.1) / 1.1 - 0.1) * 18, 2));
    glow(ctx, hx, hy, 110, C.red, 0.35 * ha);
    ctx.save();
    ctx.globalAlpha *= ha;
    I.heart(ctx, hx, hy, 70 * beat, '#d8283a', { veins: true });
    ['#4fe08a', '#ff4d5e', '#5aa8ff'].forEach((col, i) => {
      const a = t * 0.5 + (i * Math.PI * 2) / 3;
      const kx = hx + Math.cos(a) * 82, ky = hy + Math.sin(a) * 34;
      glow(ctx, kx, ky, 26, col, 0.5);
      I.key(ctx, kx, ky, 24, col);
    });
    ctx.restore();
  },
};
