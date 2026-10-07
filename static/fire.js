/* Click the page background and the dragon breathes fire at that spot. The blaze
   spreads until it covers the screen, the theme flips light <-> dark underneath it, and
   then the fire burns away. The choice is remembered (build.py's THEME_INIT reads it). */
(() => {
const svg = document.querySelector(".bg-dragon svg");
if (!svg) return;
const root = document.documentElement;
const MOUTH = { x: 12.4, y: 19.2 }; // in the glyph's 64-unit viewBox
// only empty background counts: clicks in text, links, images, or previews never set the place on fire
const SKIP = "a,button,input,textarea,select,label,summary,img,picture,iframe,video,audio,svg,.popup," +
"p,li,dt,dd,h1,h2,h3,h4,h5,h6,blockquote,pre,code,table,figure,.katex,.footnotes,.post-meta,.site-foot span";
let busy = false;

function flip() {
const dark = root.dataset.theme !== "dark";
if (dark) root.dataset.theme = "dark"; else delete root.dataset.theme;
try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch (e) {}
}

function mouth() {
const m = svg.getScreenCTM();
if (!m) return { x: innerWidth / 2, y: innerHeight / 3 };
const p = new DOMPoint(MOUTH.x, MOUTH.y).matrixTransform(m);
return { x: p.x, y: p.y };
}

// soft round flame sprites, one per age step: white-yellow core -> orange -> deep red
const STEPS = 24, SPR = 64;
let sprites = null;
function makeSprites() {
sprites = [];
for (let i = 0; i < STEPS; i++) {
const age = i / (STEPS - 1);
const r = 255, g = Math.round(235 - 200 * age), b = Math.round(150 * Math.max(0, 1 - age * 2.5));
const c = document.createElement("canvas");
c.width = c.height = SPR;
const x = c.getContext("2d");
const grad = x.createRadialGradient(SPR / 2, SPR / 2, 0, SPR / 2, SPR / 2, SPR / 2);
grad.addColorStop(0, `rgba(${r},${g},${b},1)`);
grad.addColorStop(0.4, `rgba(${r},${g},${b},0.55)`);
grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
x.fillStyle = grad;
x.fillRect(0, 0, SPR, SPR);
sprites.push(c);
}
}

function breathe(tx, ty) {
busy = true;
if (!sprites) makeSprites();
const dpr = Math.min(devicePixelRatio || 1, 1.5);
const W = innerWidth, H = innerHeight;
const cv = document.createElement("canvas");
cv.className = "fire";
cv.width = W * dpr; cv.height = H * dpr;
document.body.appendChild(cv);
const ctx = cv.getContext("2d");
ctx.scale(dpr, dpr);

const m = mouth();
const ang = Math.atan2(ty - m.y, tx - m.x);
const dist = Math.hypot(tx - m.x, ty - m.y);
const maxR = Math.max(...[[0, 0], [W, 0], [0, H], [W, H]].map(([x, y]) => Math.hypot(x - tx, y - ty))) * 1.15;
const STREAM = 380, SPREAD = 650, BURN = 700; // ms
const reach = Math.max(120, Math.min(STREAM, dist * 0.7)); // when the stream arrives at the target
const parts = [];
let t0 = 0, flipped = false, fading = false;

function spawnStream(n) {
for (let i = 0; i < n; i++) {
const a = ang + (Math.random() - 0.5) * 0.32;
const v = dist / reach * (0.8 + Math.random() * 0.45);
parts.push({ x: m.x, y: m.y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, r: 4 + Math.random() * 6,
grow: 0.05 + Math.random() * 0.05, life: 0, max: reach * (1 + Math.random() * 0.5) });
}
}
function spawnEdge(R, n, t) {
for (let i = 0; i < n; i++) {
const a = Math.random() * Math.PI * 2;
const rr = R * wob(a, t);
parts.push({ x: tx + Math.cos(a) * rr, y: ty + Math.sin(a) * rr, vx: Math.cos(a) * 0.25, vy: Math.sin(a) * 0.25 - 0.12,
r: 10 + Math.random() * 22, grow: 0.02, life: 0, max: 300 + Math.random() * 300 });
}
}
function spawnEmbers(n) {
for (let i = 0; i < n; i++) {
parts.push({ x: Math.random() * W, y: H * (0.3 + Math.random() * 0.8), vx: (Math.random() - 0.5) * 0.08,
vy: -0.15 - Math.random() * 0.25, r: 1.5 + Math.random() * 2.5, grow: 0, life: 0, max: 600 + Math.random() * 600 });
}
}
const wob = (a, t) => 1 + 0.06 * Math.sin(7 * a + t / 90) + 0.04 * Math.sin(13 * a - t / 130);

function blaze(R, t, alpha) {
if (R <= 0) return;
const g = ctx.createRadialGradient(tx, ty, 0, tx, ty, R);
g.addColorStop(0, `rgba(255,214,120,${alpha})`);
g.addColorStop(0.45, `rgba(255,128,32,${alpha})`);
g.addColorStop(0.85, `rgba(214,52,12,${alpha})`);
g.addColorStop(1, `rgba(150,20,4,${alpha})`);
ctx.fillStyle = g;
ctx.beginPath();
for (let i = 0; i <= 96; i++) {
const a = i / 96 * Math.PI * 2, rr = R * wob(a, t);
i ? ctx.lineTo(tx + Math.cos(a) * rr, ty + Math.sin(a) * rr) : ctx.moveTo(tx + Math.cos(a) * rr, ty + Math.sin(a) * rr);
}
ctx.fill();
}

let last = 0;
function frame(now) {
if (!t0) t0 = last = now;
const t = now - t0, dt = Math.min(40, now - last);
last = now;
ctx.clearRect(0, 0, W, H);

if (t < reach + 120) spawnStream(18);
let R = 0;
if (t > reach) {
const k = Math.min(1, (t - reach) / SPREAD);
R = maxR * (k * k * (3 - 2 * k)); // smoothstep
if (!flipped) spawnEdge(R, 26, t);
}
const covered = t > reach + SPREAD;
if (covered && !flipped) {
flipped = true;
flip();
spawnEmbers(90);
requestAnimationFrame(() => { fading = true; cv.style.opacity = "0"; });
setTimeout(() => { cv.remove(); busy = false; }, BURN + 60);
}

blaze(R, t, 1);
ctx.globalCompositeOperation = "lighter";
for (let i = parts.length - 1; i >= 0; i--) {
const p = parts[i];
p.life += dt;
const age = p.life / p.max;
if (age >= 1) { parts.splice(i, 1); continue; }
p.x += p.vx * dt; p.y += p.vy * dt; p.r += p.grow * dt;
p.vy -= 0.0002 * dt; // flames rise
ctx.globalAlpha = (1 - age) * 0.8;
const d = p.r * 2.4;
ctx.drawImage(sprites[Math.min(STEPS - 1, age * STEPS | 0)], p.x - d / 2, p.y - d / 2, d, d);
}
ctx.globalAlpha = 1;
ctx.globalCompositeOperation = "source-over";
if (!fading || cv.isConnected) requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
}

document.addEventListener("click", e => {
if (busy || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
if (e.target.closest && e.target.closest(SKIP)) return;
const sel = getSelection();
if (sel && !sel.isCollapsed) return; // they were selecting text, not clicking
if (matchMedia("(prefers-reduced-motion: reduce)").matches) { flip(); return; }
breathe(e.clientX, e.clientY);
});
})();
