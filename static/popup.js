/* Link previews: hover a link that has data-preview and a popup shows the target's title,
   description, and the page itself (our archived copy for external links) in a sandboxed
   frame. Pointer devices only; Escape closes. Inlined into every page by build.py. */
(() => {
  if (!matchMedia("(hover: hover) and (pointer: fine)").matches) return;
  const links = document.querySelectorAll("main a[data-preview]");
  if (!links.length) return;
  let pop = null, cur = null, showT = 0, hideT = 0;

  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  };

  function build(a) {
    const p = el("div", "popup");
    p.setAttribute("role", "dialog");
    const head = el("div", "popup-head");
    const title = el("a", "popup-title", a.dataset.title || a.href);
    title.href = a.href;
    head.appendChild(title);
    if (a.dataset.host) head.appendChild(el("span", "popup-host", a.dataset.host));
    p.appendChild(head);
    if (a.dataset.desc) p.appendChild(el("p", "popup-desc", a.dataset.desc));
    const f = el("iframe");
    f.setAttribute("sandbox", "");
    f.title = "Preview of " + (a.dataset.title || a.href);
    f.src = a.dataset.preview;
    p.appendChild(f);
    p.addEventListener("mouseenter", () => clearTimeout(hideT));
    p.addEventListener("mouseleave", scheduleHide);
    return p;
  }

  function place(a) {
    const r = a.getBoundingClientRect();
    const w = pop.offsetWidth, h = pop.offsetHeight, gap = 8, pad = 12;
    const x = Math.max(pad, Math.min(r.left, innerWidth - w - pad));
    const fitsBelow = innerHeight - r.bottom >= h + gap + pad;
    const fitsAbove = r.top >= h + gap + pad;
    const y = fitsBelow || !fitsAbove ? r.bottom + gap : r.top - gap - h;
    pop.style.left = x + scrollX + "px";
    pop.style.top = y + scrollY + "px";
  }

  function show(a) {
    if (cur === a) return;
    hide();
    pop = build(a);
    cur = a;
    document.body.appendChild(pop);
    place(a); // reads layout, so the fade-in below starts from opacity 0
    pop.classList.add("on");
  }

  function hide() {
    clearTimeout(showT);
    clearTimeout(hideT);
    if (pop) pop.remove();
    pop = cur = null;
  }

  function scheduleHide() {
    clearTimeout(hideT);
    hideT = setTimeout(hide, 250);
  }

  for (const a of links) {
    a.addEventListener("mouseenter", () => {
      clearTimeout(hideT);
      clearTimeout(showT);
      showT = setTimeout(() => show(a), 350);
    });
    a.addEventListener("mouseleave", () => {
      clearTimeout(showT);
      scheduleHide();
    });
  }
  addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
  addEventListener("resize", () => { if (cur) place(cur); });
})();
