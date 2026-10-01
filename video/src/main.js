// Preview player and renderer entry point.
// Preview: index.html            (choose a segment, play / scrub)
// Render:  index.html?render=1   (driven by tools/render.mjs through window.__setup / __frame)
import { renderScene, ensureFonts } from './engine.js';
import { VIDEO } from './config.js';
import { SCENES } from './scenes/index.js';

const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const params = new URLSearchParams(location.search);
const byId = Object.fromEntries(SCENES.map((s) => [s.id, s]));

let current = byId[params.get('scene')] ?? SCENES[0];

// Draw the scene at many sample times so every string's font files are requested
// before the first real frame is kept.
async function preload(scene) {
  await document.fonts.ready;
  for (let t = 0; t <= scene.duration; t += 1 / 12) renderScene(ctx, scene, t);
  while (await ensureFonts()) {
    renderScene(ctx, scene, 0);
  }
}

async function frame(t) {
  renderScene(ctx, current, t);
  // A string not seen during preload: load its glyphs and redraw.
  while (await ensureFonts()) renderScene(ctx, current, t);
}

window.__list = () => SCENES.map((s) => ({ id: s.id, num: s.num, title: s.title, duration: s.duration, file: s.file }));
window.__setup = async (id) => {
  current = byId[id];
  await preload(current);
  return true;
};
window.__frame = async (t, asData) => {
  await frame(t);
  if (asData) return canvas.toDataURL('image/png');
  return true;
};

if (params.get('render')) {
  document.body.classList.add('render');
} else {
  setupPlayer();
}

function setupPlayer() {
  const list = document.getElementById('scenes');
  const playBtn = document.getElementById('play');
  const scrub = document.getElementById('scrub');
  const time = document.getElementById('time');
  let t = Number(params.get('t') ?? 0);
  let playing = !params.get('t');
  let last = performance.now();
  let ready = false;

  async function select(scene) {
    current = scene;
    ready = false;
    [...list.children].forEach((b) => b.classList.toggle('on', b.dataset.id === scene.id));
    history.replaceState(null, '', `?scene=${scene.id}`);
    await preload(scene);
    ready = true;
    t = 0;
    last = performance.now();
  }

  for (const s of SCENES) {
    const b = document.createElement('button');
    b.textContent = `${s.num} ${s.title}`;
    b.dataset.id = s.id;
    b.onclick = () => select(s);
    list.appendChild(b);
  }
  playBtn.onclick = () => {
    playing = !playing;
    last = performance.now();
  };
  document.getElementById('back').onclick = () => { playing = false; t = Math.max(0, t - 1 / VIDEO.fps); };
  document.getElementById('fwd').onclick = () => { playing = false; t = Math.min(current.duration, t + 1 / VIDEO.fps); };
  scrub.oninput = () => {
    playing = false;
    t = (scrub.value / 1000) * current.duration;
  };
  window.addEventListener('keydown', (e) => {
    if (e.code === 'Space') { e.preventDefault(); playBtn.click(); }
    if (e.code === 'ArrowRight') document.getElementById('fwd').click();
    if (e.code === 'ArrowLeft') document.getElementById('back').click();
  });

  function tick(now) {
    if (ready) {
      if (playing) {
        t += (now - last) / 1000;
        if (t > current.duration) t = 0;
      }
      renderScene(ctx, current, t);
      ensureFonts();
      scrub.value = String(Math.round((t / current.duration) * 1000));
      time.textContent = `${t.toFixed(2)} / ${current.duration.toFixed(2)}`;
      playBtn.textContent = playing ? '暂停' : '播放';
    }
    last = now;
    requestAnimationFrame(tick);
  }
  select(current).then(() => {
    if (params.get('t')) t = Number(params.get('t'));
  });
  requestAnimationFrame(tick);
}
