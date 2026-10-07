/* Click the page background and the dragon breathes fire at that spot. Drawn like the glyph
   and the initials: flat flame tongues in the site's fire colour with woodcut cut-outs, no
   gradients or glow. A wall of flame spreads until it covers the screen, the theme flips
   light <-> dark underneath it, then the fire burns out in patches across the new theme.
   The choice is remembered (build.py's THEME_INIT reads it). */
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

const ease = k => k * k * (3 - 2 * k);

// a flame tongue pointing along +x from (0,0): round head of radius r, tail curling back to (-len, sway)
function tongue(ctx, r, len, sway) {
ctx.moveTo(-len, sway);
ctx.quadraticCurveTo(-len * 0.45, -r * 1.15 + sway * 0.5, 0, -r);
ctx.arc(0, 0, r, -Math.PI / 2, Math.PI / 2);
ctx.quadraticCurveTo(-len * 0.35, r * 0.9 + sway * 0.6, -len, sway);
}

function breathe(tx, ty) {
busy = true;
const dpr = Math.min(devicePixelRatio || 1, 2);
const W = innerWidth, H = innerHeight;
const cv = document.createElement("canvas");
cv.className = "fire";
cv.width = W * dpr; cv.height = H * dpr;
document.body.appendChild(cv);
const ctx = cv.getContext("2d");
ctx.scale(dpr, dpr);
const FIRE = getComputedStyle(root).getPropertyValue("--fire").trim() || "#bf3f1b";

const m = mouth();
const ang = Math.atan2(ty - m.y, tx - m.x);
const dist = Math.hypot(tx - m.x, ty - m.y);
const LICK = Math.min(110, Math.max(60, Math.min(W, H) * 0.12)); // how far flame tips reach past the wall
const maxR = Math.max(...[[0, 0], [W, 0], [0, H], [W, H]].map(([x, y]) => Math.hypot(x - tx, y - ty))) + LICK * 2.2;
const STREAM = 380, SPREAD = 620, HOLD = 120; // ms
const reach = Math.max(140, Math.min(STREAM, dist * 0.7)); // when the breath arrives at the target
const seeds = n => Array.from({ length: n }, () => ({ ph: Math.random() * 6.28, h: 0.65 + Math.random() * 0.35, c: Math.random() - 0.3 }));
const big = seeds(15);
let t0 = 0, flipped = false;

// circle of radius R at (cx, cy) whose rim is a ring of curling flame licks of height up to lick
function wall(cx, cy, R, t, spin, sd, lick) {
const n = sd.length, sp = Math.PI * 2 / n, h = Math.min(lick, R * 0.5);
const P = (a, r) => [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
ctx.beginPath();
for (let i = 0; i < n; i++) {
const s = sd[i], a0 = i * sp + spin, hh = h * s.h * (0.8 + 0.2 * Math.sin(t / 70 + s.ph));
const at = a0 + sp * (0.55 + 0.45 * s.c), a1 = a0 + sp;
const [x0, y0] = P(a0, R), [xt, yt] = P(at, R + hh), [x1, y1] = P(a1, R);
const [c1x, c1y] = P(a0 + sp * 0.02, R + hh * 0.5), [c2x, c2y] = P(at - sp * 0.4, R + hh * 0.8);
const [c3x, c3y] = P(at + sp * 0.1, R + hh * 0.5), [c4x, c4y] = P(a1 - sp * 0.1, R + hh * 0.2);
i ? ctx.lineTo(x0, y0) : ctx.moveTo(x0, y0);
ctx.bezierCurveTo(c1x, c1y, c2x, c2y, xt, yt);
ctx.bezierCurveTo(c3x, c3y, c4x, c4y, x1, y1);
}
ctx.closePath();
ctx.fill();
}
// small tongues pointing outward just inside a wall, like the cut-outs in the glyph
function tongues(cx, cy, R, t, spin, scale, sd, lick) {
const n = sd.length, sp = Math.PI * 2 / n, r = Math.min(lick, R * 0.5) * 0.17 * scale;
if (r < 1) return;
for (let i = 0; i < n; i++) {
const s = sd[i], a = i * sp + spin + sp * 0.5, rr = R - r * 2.2;
ctx.save();
ctx.translate(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr);
ctx.rotate(a + Math.PI);
ctx.beginPath();
tongue(ctx, r, r * 4.2, r * 1.6 * Math.sin(t / 90 + s.ph));
ctx.fill();
ctx.restore();
}
}

// the burn-out: patches on a jittered grid, each a flame-edged hole that opens on the new
// theme. Patches near the click go first, so the fire dies back across the page unevenly.
const CELL = Math.max(130, Math.min(240, Math.max(W, H) / 7));
const PLICK = CELL * 0.3, GROW = 1300, STAGGER = 2600;
const far = Math.hypot(W, H);
const spots = [];
for (let y = -CELL / 2; y < H + CELL; y += CELL)
for (let x = -CELL / 2; x < W + CELL; x += CELL) {
const sx = x + (Math.random() - 0.5) * CELL * 0.6, sy = y + (Math.random() - 0.5) * CELL * 0.6;
const at = Math.min(1, Math.hypot(sx - tx, sy - ty) / far) * STAGGER * 0.65 + Math.random() * STAGGER * 0.35;
spots.push({ x: sx, y: sy, at, spin: Math.random() * 6.28, sd: seeds(8) });
}

function frame(now) {
if (!t0) t0 = now;
const t = now - t0;
ctx.clearRect(0, 0, W, H);
ctx.fillStyle = FIRE;

// the breath: one tapering jet from the mouth to the target, its edges trailing flame licks
if (!flipped) {
const len = dist * ease(Math.min(1, t / reach)), WMAX = Math.min(72, 20 + dist * 0.08);
if (len > 2) {
const w = x => 3 + Math.pow(x / len, 0.8) * WMAX;
// rounded licks that lean back toward the mouth, rolling forward along the jet
const lick = (x, ph) => { let f = (x / 46 - t / 40 + ph) % 1; if (f < 0) f += 1; return 0.5 - 0.5 * Math.cos(2 * Math.PI * Math.pow(f, 1.8)); };
ctx.save();
ctx.translate(m.x, m.y);
ctx.rotate(ang);
ctx.beginPath();
ctx.moveTo(0, 0);
for (let x = 0; x <= len; x += 2) ctx.lineTo(x, -w(x) / 2 * (1 + 0.7 * lick(x, 0)));
ctx.arc(len, 0, w(len) / 2, -Math.PI / 2, Math.PI / 2);
for (let x = len; x >= 0; x -= 2) ctx.lineTo(x, w(x) / 2 * (1 + 0.7 * lick(x, 0.5)));
ctx.closePath();
ctx.fill();
ctx.globalCompositeOperation = "destination-out";
for (const f of [0.35, 0.58, 0.8]) {
const x = len * f - (t / 4) % 30, r = w(x) * 0.2;
if (x < 20 || r < 1.5) continue;
ctx.save();
ctx.translate(x, Math.sin(t / 80 + f * 9) * w(x) * 0.12);
ctx.rotate(Math.PI);
ctx.beginPath();
tongue(ctx, r, r * 4, r * 1.2 * Math.sin(t / 70 + f * 5));
ctx.fill();
ctx.restore();
}
ctx.restore();
}
}

// the wall of flame
if (t > reach && !flipped) {
const k = Math.min(1, (t - reach) / SPREAD), R = maxR * ease(k);
wall(tx, ty, R, t, t / 1800, big, LICK);
ctx.globalCompositeOperation = "destination-out";
tongues(tx, ty, R, t, t / 1800, 1 - k, big, LICK);
ctx.globalCompositeOperation = "source-over";
}
if (t >= reach + SPREAD && !flipped) { flipped = true; flip(); }

// then it burns out, patch by patch, onto the new theme
if (flipped) {
const tr = t - (reach + SPREAD + HOLD);
ctx.fillRect(0, 0, W, H);
let done = true;
for (const s of spots) {
const k = Math.max(0, Math.min(1, (tr - s.at) / GROW));
if (k < 1) done = false;
if (k <= 0) continue;
const R = CELL * 1.05 * (1 - Math.pow(1 - k, 2)); // fast catch, slow finish
ctx.globalCompositeOperation = "destination-out";
wall(s.x, s.y, R, t, s.spin + t / 2400, s.sd, PLICK);
ctx.globalCompositeOperation = "source-over";
tongues(s.x, s.y, R, t, s.spin, 1 - k, s.sd, PLICK);
}
if (done) { cv.remove(); busy = false; return; }
}
requestAnimationFrame(frame);
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
