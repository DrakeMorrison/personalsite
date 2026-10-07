/* Home-page background dragon: its pupil follows the pointer. */
(() => {
const eye = document.getElementById("dragon-eye");
const pupil = document.getElementById("dragon-pupil");
if (!eye || !pupil) return;
// rest position and reach, in the glyph's 64-unit viewBox
const cx = 23.4, cy = 13.6, rx = 1.25, ry = 0.7;
let tx = 0, ty = 0, x = 0, y = 0, raf = 0;
const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
function draw() {
x += (tx - x) * 0.25;
y += (ty - y) * 0.25;
if (still || (Math.abs(tx - x) < 0.001 && Math.abs(ty - y) < 0.001)) { x = tx; y = ty; raf = 0; }
else raf = requestAnimationFrame(draw);
pupil.setAttribute("cx", (cx + x * rx).toFixed(3));
pupil.setAttribute("cy", (cy + y * ry).toFixed(3));
}
function look(px, py) {
const r = eye.getBoundingClientRect();
const dx = px - (r.left + r.width / 2), dy = py - (r.top + r.height / 2);
const d = Math.hypot(dx, dy) || 1;
const k = Math.min(1, d / (r.width * 4));
tx = dx / d * k;
ty = dy / d * k;
if (!raf) raf = requestAnimationFrame(draw);
}
addEventListener("pointermove", e => look(e.clientX, e.clientY), { passive: true });
addEventListener("pointerdown", e => look(e.clientX, e.clientY), { passive: true });
document.documentElement.addEventListener("pointerleave", () => { tx = ty = 0; if (!raf) raf = requestAnimationFrame(draw); });
})();
