// Frame-exact renderer: drives index.html?render=1 in headless Chromium, saves
// PNG frames and encodes each segment to H.264 MP4 with ffmpeg.
//
//   node tools/render.mjs                      all segments + full reel
//   node tools/render.mjs --only s03,s04       selected segments
//   node tools/render.mjs --only s11 --reel    re-render one segment and rebuild the full reel
//   node tools/render.mjs --fps 30             override frame rate
//   node tools/render.mjs --sheet s04 [--n 12] contact sheet of evenly spaced frames
//   node tools/render.mjs --still s04 --at 2.5,6  single PNG frames
import { chromium } from 'playwright';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { serve } from './serve.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
const arg = (name, dflt) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 ? argv[i + 1] : dflt;
};
const flag = (name) => argv.includes(`--${name}`);

const fps = Number(arg('fps', 60));
const workers = Number(arg('workers', Math.max(1, Math.min(6, os.cpus().length))));
const outDir = path.resolve(ROOT, arg('out', 'out'));
const tmpRoot = path.resolve(arg('tmp', path.join(os.tmpdir(), 'sts-video-frames')));
fs.mkdirSync(outDir, { recursive: true });

function ffmpeg(args) {
  const r = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', ...args], { stdio: 'inherit' });
  if (r.status !== 0) throw new Error(`ffmpeg failed: ${args.join(' ')}`);
}

const ENCODE = [
  '-c:v', 'libx264', '-preset', 'slow', '-crf', '15', '-tune', 'animation',
  '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p',
  '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
  '-movflags', '+faststart',
];

const server = await serve(0);
const url = `http://127.0.0.1:${server.address().port}/index.html?render=1`;

async function openPage() {
  const browser = await chromium.launch({
    args: ['--font-render-hinting=none', '--force-color-profile=srgb', '--disable-lcd-text'],
  });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  page.on('pageerror', (e) => console.error('[page error]', e.message));
  page.on('console', (m) => {
    if (m.type() === 'error') console.error('[console]', m.text());
  });
  await page.goto(url);
  await page.waitForFunction(() => typeof window.__frame === 'function');
  return { browser, page };
}

async function grab(page, t, file) {
  const data = await page.evaluate(async (tt) => window.__frame(tt, true), t);
  fs.writeFileSync(file, Buffer.from(data.slice(data.indexOf(',') + 1), 'base64'));
}

const pool = await Promise.all(Array.from({ length: workers }, openPage));
const scenes = await pool[0].page.evaluate(() => window.__list());
const byId = Object.fromEntries(scenes.map((s) => [s.id, s]));

async function setupAll(id) {
  await Promise.all(pool.map(({ page }) => page.evaluate((x) => window.__setup(x), id)));
}

async function renderFrames(scene, times, dir) {
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  await setupAll(scene.id);
  let done = 0;
  const started = Date.now();
  await Promise.all(
    pool.map(async ({ page }, w) => {
      for (let i = w; i < times.length; i += pool.length) {
        await grab(page, times[i], path.join(dir, `${String(i).padStart(5, '0')}.png`));
        done++;
        if (done % 120 === 0) {
          const rate = done / ((Date.now() - started) / 1000);
          process.stdout.write(`\r  ${scene.id} ${done}/${times.length} frames (${rate.toFixed(1)} fps)   `);
        }
      }
    }),
  );
  process.stdout.write('\n');
}

try {
  if (arg('sheet')) {
    const scene = byId[arg('sheet')];
    const n = Number(arg('n', 12));
    const times = Array.from({ length: n }, (_, i) => +(0.4 + (i * (scene.duration - 0.8)) / (n - 1)).toFixed(3));
    const dir = path.join(tmpRoot, `sheet-${scene.id}`);
    await renderFrames(scene, times, dir);
    const cols = 4;
    const file = path.join(outDir, `sheet-${scene.id}.png`);
    ffmpeg(['-i', path.join(dir, '%05d.png'), '-vf', `scale=640:-1,tile=${cols}x${Math.ceil(n / cols)}:padding=6:color=black`, '-frames:v', '1', file]);
    console.log(`${file}\n  times: ${times.join(', ')}`);
  } else if (arg('still')) {
    const scene = byId[arg('still')];
    const times = String(arg('at', '1')).split(',').map(Number);
    const dir = path.join(outDir, 'stills');
    fs.mkdirSync(dir, { recursive: true });
    await setupAll(scene.id);
    for (const t of times) {
      const file = path.join(dir, `${scene.id}-${t.toFixed(2)}.png`);
      await grab(pool[0].page, t, file);
      console.log(file);
    }
  } else {
    const only = arg('only') ? arg('only').split(',') : scenes.map((s) => s.id);
    const made = [];
    for (const id of only) {
      const scene = byId[id];
      if (!scene) throw new Error(`unknown segment ${id}`);
      const count = Math.round(scene.duration * fps);
      const times = Array.from({ length: count }, (_, i) => i / fps);
      const dir = path.join(tmpRoot, scene.id);
      const t0 = Date.now();
      console.log(`${scene.num} ${scene.title}: ${count} frames @ ${fps} fps`);
      await renderFrames(scene, times, dir);
      const file = path.join(outDir, `${scene.file}.mp4`);
      ffmpeg(['-framerate', String(fps), '-i', path.join(dir, '%05d.png'), ...ENCODE, '-r', String(fps), file]);
      fs.rmSync(dir, { recursive: true, force: true });
      console.log(`  -> ${path.relative(ROOT, file)} (${((Date.now() - t0) / 1000).toFixed(0)} s)`);
      made.push(file);
    }
    if ((!arg('only') || flag('reel')) && !flag('no-reel')) {
      const list = path.join(tmpRoot, 'reel.txt');
      fs.writeFileSync(list, scenes.map((s) => `file '${path.join(outDir, `${s.file}.mp4`)}'`).join('\n'));
      const reel = path.join(outDir, '00-full-reel.mp4');
      ffmpeg(['-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', '-movflags', '+faststart', reel]);
      console.log(`  -> ${path.relative(ROOT, reel)}`);
    }
  }
} finally {
  await Promise.all(pool.map(({ browser }) => browser.close()));
  server.close();
}
