#!/usr/bin/env python3
"""Static site generator for drakemorrison.net.

    python3 build.py            # render posts/, pages/, static/ -> docs/
    python3 build.py --serve    # then preview at http://localhost:8000/
    python3 build.py --check    # validate frontmatter, links, archives, images
    python3 build.py --proof    # also write docs/_proof/dropcaps.html
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import markdown
import yaml
from bs4 import BeautifulSoup, NavigableString, Tag
from PIL import Image

ROOT = Path(__file__).resolve().parent
SITE_URL = "https://drakemorrison.net"
SITE_NAME = "Drake Morrison"
AUTHOR = "Drake Morrison"
REPO = "DrakeMorrison/personalsite"
OUT = ROOT / "docs"
POSTS = ROOT / "posts"
PAGES = ROOT / "pages"
STATIC = ROOT / "static"
SRC_ASSETS = ROOT / "src-assets"
ARCHIVE_FILE = ROOT / "archive.json"
MAX_IMAGE_WIDTH = 1400
WPM = 250
EXTERNAL_NEW_TAB = False
LATIN_RANGE = ("U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,"
               "U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD")

written: set[Path] = set()
warnings: list[str] = []


def warn(msg: str) -> None:
    warnings.append(msg)
    print("warning:", msg, file=sys.stderr)


# ----------------------------------------------------------------------------- documents

@dataclass
class Doc:
    slug: str
    kind: str  # "post" | "page"
    title: str
    date: dt.date | None
    updated: dt.date | None
    description: str
    body_md: str
    meta: dict
    canonical: str = ""
    draft: bool = False
    tags: list[str] = field(default_factory=list)
    dropcap: bool = True
    template: str = "post"
    title_html: str = ""
    body_html: str = ""
    text: str = ""
    words: int = 0
    minutes: int = 0
    has_dropcap: bool = False
    images: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        if self.kind == "post":
            return f"/essays/{self.slug}/"
        return "/" if self.slug == "index" else f"/{self.slug}/"

    @property
    def out_path(self) -> Path:
        return OUT / self.url.strip("/") / "index.html"


def to_date(v) -> dt.date | None:
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


def load_doc(path: Path, kind: str) -> Doc:
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?", raw, re.S)
    if not m:
        raise SystemExit(f"{path}: missing frontmatter")
    meta = yaml.safe_load(m.group(1)) or {}
    body = raw[m.end():]
    for key in ("title", "description"):
        if not meta.get(key):
            raise SystemExit(f"{path}: frontmatter needs '{key}'")
    if kind == "post" and not meta.get("date"):
        raise SystemExit(f"{path}: posts need a 'date'")
    return Doc(
        slug=path.stem,
        kind=kind,
        title=str(meta["title"]),
        date=to_date(meta.get("date")),
        updated=to_date(meta.get("updated")),
        description=str(meta["description"]),
        body_md=body,
        meta=meta,
        canonical=str(meta.get("canonical") or ""),
        draft=bool(meta.get("draft", False)),
        tags=list(meta.get("tags") or []),
        dropcap=bool(meta.get("dropcap", kind == "post")),
        template=str(meta.get("template") or ("post" if kind == "post" else "page")),
    )


def collect(include_drafts: bool) -> tuple[list[Doc], list[Doc]]:
    posts = [load_doc(p, "post") for p in sorted(POSTS.glob("*.md"))]
    posts = [p for p in posts if include_drafts or not p.draft]
    posts.sort(key=lambda d: (d.date, d.slug), reverse=True)
    pages = [load_doc(p, "page") for p in sorted(PAGES.glob("*.md"))]
    pages = [p for p in pages if include_drafts or not p.draft]
    return posts, pages


# ----------------------------------------------------------------------------- markdown

MD = markdown.Markdown(
    extensions=["footnotes", "toc", "smarty", "attr_list", "tables", "fenced_code", "md_in_html", "sane_lists"],
    extension_configs={
        "footnotes": {
            "BACKLINK_TEXT": "&#8617;",
            "BACKLINK_TITLE": "Back to reference {}",
            "UNIQUE_IDS": False,
            "USE_DEFINITION_ORDER": True,
        },
        "toc": {"baselevel": 2, "anchorlink": False, "permalink": False},
        "smarty": {"smart_quotes": True, "smart_dashes": True, "smart_ellipses": True},
    },
    output_format="html",
)


def render_markdown(text: str) -> str:
    MD.reset()
    return MD.convert(text)


def smarten(text: str) -> str:
    """Inline markdown (smart quotes, emphasis) for titles and descriptions."""
    out = render_markdown(text.strip())
    out = re.sub(r"^<p>|</p>$", "", out.strip())
    return out


def plain(text_html: str) -> str:
    return BeautifulSoup(text_html, "html.parser").get_text()


# ----------------------------------------------------------------------------- assets

MANIFEST_PATH = OUT / "assets" / "manifest.json"
_manifest: dict | None = None


def manifest() -> dict:
    global _manifest
    if _manifest is None:
        _manifest = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}
    return _manifest


def encode_image(rel: str, max_width: int = MAX_IMAGE_WIDTH) -> dict | None:
    """rel is '<slug>/<name>.<ext>' under src-assets/. Returns {"webp","avif","w","h"} or None."""
    src = SRC_ASSETS / rel
    if not src.exists():
        warn(f"missing image src-assets/{rel}")
        return None
    out_dir = OUT / "assets" / Path(rel).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(rel).stem
    ext = src.suffix.lower()
    if ext in (".svg", ".gif"):
        dest = out_dir / src.name
        shutil.copyfile(src, dest)
        written.add(dest)
        with Image.open(src) if ext == ".gif" else _svg_size(src) as im:
            w, h = im.size
        return {"src": f"/assets/{rel}", "w": w, "h": h}
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    key = f"{rel}|{max_width}"
    entry = manifest().get(key)
    webp = out_dir / f"{stem}.webp"
    avif = out_dir / f"{stem}.avif"
    if not (entry and entry.get("sha256") == digest and webp.exists() and avif.exists()):
        print(f"  encoding {rel}")
        common = [str(src), "-auto-orient", "-strip", "-resize", f"{max_width}x>"]
        subprocess.run(["magick", *common, "-quality", "80", "-define", "webp:method=6", str(webp)], check=True)
        avif_opts = ["-quality", "60", "-define", "heic:speed=6"]
        if ext == ".png":
            avif_opts += ["-define", "heic:chroma=444"]
        subprocess.run(["magick", *common, *avif_opts, str(avif)], check=True)
        with Image.open(webp) as im:
            w, h = im.size
        manifest()[key] = {"sha256": digest, "w": w, "h": h}
    else:
        w, h = entry["w"], entry["h"]
    written.update({webp, avif})
    parent = Path(rel).parent.as_posix()
    return {"webp": f"/assets/{parent}/{stem}.webp", "avif": f"/assets/{parent}/{stem}.avif", "w": w, "h": h}


class _svg_size:
    def __init__(self, path: Path):
        root = ET.parse(path).getroot()
        vb = (root.get("viewBox") or "0 0 0 0").split()
        self.size = (int(float(root.get("width") or vb[2])), int(float(root.get("height") or vb[3])))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ----------------------------------------------------------------------------- post-processing

_archive: dict | None = None


def archive() -> dict:
    global _archive
    if _archive is None:
        _archive = json.loads(ARCHIVE_FILE.read_text()) if ARCHIVE_FILE.exists() else {}
    return _archive


_snapshot_meta: dict[str, tuple[str, str]] = {}
_ATTR_RE = re.compile(r"""([\w:-]+)=(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")


def snapshot_meta(local: str) -> tuple[str, str]:
    """(title, description) read from the head of an archived copy under static/archive/."""
    if local not in _snapshot_meta:
        title = desc = ""
        path = STATIC / "archive" / local.removeprefix("/archive/")
        if path.suffix == ".html" and path.exists():
            head = path.read_text(encoding="utf-8", errors="replace")
            if m := re.search(r"<title[^>]*>(.*?)</title>", head, re.I | re.S):
                title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
            metas = {}
            for tag in re.findall(r"<meta\b[^>]*>", head, re.I):
                attrs = {k.lower(): html.unescape(v1 or v2 or v3) for k, v1, v2, v3 in _ATTR_RE.findall(tag)}
                key = attrs.get("name") or attrs.get("property")
                if key and "content" in attrs:
                    metas.setdefault(key.lower(), attrs["content"].strip())
            desc = metas.get("description") or metas.get("og:description") or ""
        _snapshot_meta[local] = (title, desc)
    return _snapshot_meta[local]


docs_by_url: dict[str, "Doc"] = {}


def is_external(href: str) -> bool:
    return href.startswith(("http://", "https://")) and not href.startswith(SITE_URL)


DRAGON_USE = '<svg class="dragon" aria-hidden="true"><use href="#dragon"/></svg>'


def tidy_paragraphs(soup: BeautifulSoup) -> None:
    for p in soup.find_all("p"):
        while p.contents and isinstance(p.contents[-1], NavigableString) and not p.contents[-1].strip():
            p.contents[-1].extract()
        if not p.get_text(strip=True) and not p.find(True):
            p.decompose()
            continue
        if p.parent is soup:
            t = p.get_text().strip()
            if t.startswith("(") and t.endswith(")"):
                p["class"] = p.get("class", []) + ["note"]


def apply_dropcap(soup: BeautifulSoup, doc: Doc) -> None:
    if not doc.dropcap:
        return
    for p in soup.find_all("p", recursive=False):
        if "note" in p.get("class", []):
            continue
        node = p.contents[0] if p.contents else None
        if not isinstance(node, NavigableString):
            return
        m = re.match(r'^(["\'“‘]?)([A-Z])', str(node))
        if not m:
            return
        quote, letter = m.group(1), m.group(2)
        rest = str(node)[m.end():]
        span = soup.new_tag("span", attrs={"class": "dropcap", "data-l": letter})
        span.string = letter
        node.replace_with(NavigableString(quote) if quote else NavigableString(""))
        p.contents[0].insert_after(span)
        span.insert_after(NavigableString(rest))
        if not quote:
            p.contents[0].extract()
        doc.has_dropcap = True
        return


def rewrite_images(soup: BeautifulSoup, doc: Doc) -> None:
    first = True
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src.startswith("/assets/"):
            warn(f"{doc.slug}: image not self-hosted: {src}")
            continue
        rel = src[len("/assets/"):]
        info = encode_image(rel)
        if info is None:
            continue
        doc.images.append(src)
        fig = soup.new_tag("figure")
        new_img = soup.new_tag("img", attrs={
            "src": info.get("webp") or info["src"],
            "width": str(info["w"]),
            "height": str(info["h"]),
            "alt": img.get("alt", ""),
            "decoding": "async",
        })
        if first:
            new_img["loading"] = "eager"
            new_img["fetchpriority"] = "high"
            first = False
        else:
            new_img["loading"] = "lazy"
        if "avif" in info:
            pic = soup.new_tag("picture")
            source = soup.new_tag("source", attrs={"type": "image/avif", "srcset": info["avif"]})
            pic.append(source)
            pic.append(new_img)
            fig.append(pic)
        else:
            fig.append(new_img)
        if img.get("title"):
            cap = soup.new_tag("figcaption")
            cap.string = img["title"]
            fig.append(cap)
        parent = img.parent
        if parent.name == "p" and not parent.get_text(strip=True) and len(parent.find_all(True)) == 1:
            parent.replace_with(fig)
        else:
            img.replace_with(fig)


def decorate_links(soup: BeautifulSoup, marks: bool = True) -> None:
    """rel=noopener on external links; with marks=True also add the archive mark."""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not is_external(href):
            continue
        rel = set((a.get("rel") or []))
        rel.add("noopener")
        a["rel"] = sorted(rel)
        if EXTERNAL_NEW_TAB:
            a["target"] = "_blank"
        if not marks or "web.archive.org" in href or "footnote-backref" in a.get("class", []):
            continue
        entry = archive().get(href)
        if entry and entry.get("status") == "ok":
            # prefer our own copy (served from /archive/), fall back to the Wayback Machine
            if entry.get("local"):
                target, when = entry["local"], dt.date.fromisoformat(entry["fetched"]).strftime("%-d %B %Y")
            else:
                ts = entry.get("timestamp", "")
                target = entry["archived"]
                when = dt.datetime.strptime(ts[:8], "%Y%m%d").strftime("%-d %B %Y") if ts else ""
            arc = soup.new_tag("a", attrs={"class": "arc", "href": target, "rel": "nofollow",
                                            "title": f"Archived copy, {when}" if when else "Archived copy"})
            arc.string = "a"
            a.insert_after(arc)
            if entry.get("local", "").endswith(".html"):
                title, desc = snapshot_meta(entry["local"])
                a["data-preview"] = entry["local"]
                a["data-host"] = re.sub(r"^www\.", "", urlparse(href).hostname or "")
                if title:
                    a["data-title"] = title
                if desc:
                    a["data-desc"] = desc


def preview_internal_links(soup: BeautifulSoup) -> None:
    """Essay-to-essay links preview the target essay."""
    for a in soup.find_all("a", href=True):
        path = a["href"].split("#")[0]
        target = docs_by_url.get(path)
        if target and target.kind == "post" and "footnote-backref" not in a.get("class", []):
            a["data-preview"] = path
            a["data-title"] = target.title
            a["data-desc"] = target.description


def replace_hr(soup: BeautifulSoup) -> None:
    for hr in soup.find_all("hr"):
        if hr.find_parent("div", class_="footnote"):
            continue
        div = soup.new_tag("div", attrs={"class": "divider", "role": "separator"})
        div.append(BeautifulSoup(DRAGON_USE, "html.parser"))
        hr.replace_with(div)


def fix_footnotes(soup: BeautifulSoup) -> None:
    fn = soup.find("div", class_="footnote")
    if not fn:
        return
    fn.name = "section"
    fn["class"] = ["footnotes"]
    fn["role"] = "doc-endnotes"
    fn["aria-label"] = "Footnotes"
    for hr in fn.find_all("hr"):
        hr.decompose()
    for a in fn.find_all("a", class_="footnote-backref"):
        a["role"] = "doc-backlink"
    for a in soup.find_all("a", class_="footnote-ref"):
        a["role"] = "doc-noteref"


def strip_embeds(soup: BeautifulSoup, doc: Doc) -> None:
    for tag in soup.find_all(["iframe", "script", "embed", "object"]):
        src = tag.get("src") or tag.get("data") or ""
        warn(f"{doc.slug}: replaced <{tag.name}> with a link ({src})")
        if src:
            a = soup.new_tag("a", href=src)
            a.string = src
            p = soup.new_tag("p")
            p.append(a)
            tag.replace_with(p)
        else:
            tag.decompose()


def wrap_tables(soup: BeautifulSoup) -> None:
    for t in soup.find_all("table"):
        wrap = soup.new_tag("div", attrs={"class": "table-wrap"})
        t.wrap(wrap)


def postprocess(doc: Doc) -> None:
    soup = BeautifulSoup(doc.body_html, "html.parser")
    tidy_paragraphs(soup)
    apply_dropcap(soup, doc)
    rewrite_images(soup, doc)
    # archive marks are for citations in essays; pages (home, gifts, ...) are navigational
    decorate_links(soup, marks=bool(doc.meta.get("archive_marks", doc.kind == "post")))
    preview_internal_links(soup)
    replace_hr(soup)
    fix_footnotes(soup)
    strip_embeds(soup, doc)
    wrap_tables(soup)
    doc.body_html = soup.decode(formatter="minimal")
    doc.text = soup.get_text(" ")
    doc.words = len(doc.text.split())
    doc.minutes = max(1, round(doc.words / WPM))


# ----------------------------------------------------------------------------- templates

def css_min(css: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"\s+", " ", css)
    css = re.sub(r"\s*([{};:,>])\s*", r"\1", css)
    return css.replace(";}", "}").strip()


_css: str | None = None


def site_css() -> str:
    global _css
    if _css is None:
        _css = css_min((STATIC / "style.css").read_text(encoding="utf-8"))
    return _css


_js: str | None = None


def site_js() -> str:
    global _js
    if _js is None:
        js = (STATIC / "popup.js").read_text(encoding="utf-8")
        js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        _js = "\n".join(line.strip() for line in js.splitlines() if line.strip())
    return _js


_dragon: str | None = None


def dragon_symbol() -> str:
    global _dragon
    if _dragon is None:
        svg = (STATIC / "dragon.svg").read_text(encoding="utf-8")
        root = ET.fromstring(svg)
        vb = root.get("viewBox", "0 0 64 64")
        inner = "".join(ET.tostring(c, encoding="unicode") for c in root)
        inner = re.sub(r' xmlns(:\w+)?="[^"]*"', "", inner)
        inner = re.sub(r"<(/?)(?:ns\d+|svg):", r"<\1", inner)
        _dragon = (f'<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false">'
                   f'<symbol id="dragon" viewBox="{vb}">{inner}</symbol></svg>')
    return _dragon


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def fmt_date(d: dt.date, short: bool = False) -> str:
    return d.strftime("%b %-d, %Y") if short else d.strftime("%B %-d, %Y")


def font_preloads(*names: str) -> str:
    return "".join(
        f'<link rel="preload" href="/fonts/EBGaramond-{n}.woff2" as="font" type="font/woff2" crossorigin>'
        for n in names
    )


def page_shell(*, title: str, description: str, body: str, url: str, kind: str = "page",
               extra_head: str = "", fonts: tuple[str, ...] = ("Regular",)) -> str:
    full_title = title if url == "/" else f"{title} · {SITE_NAME}"
    abs_url = SITE_URL + url
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="author" content="{esc(AUTHOR)}">
<link rel="canonical" href="{abs_url}">
<link rel="icon" href="/favicon.ico">
<link rel="alternate" type="application/atom+xml" title="{esc(SITE_NAME)}" href="/feed.xml">
<meta property="og:site_name" content="{esc(SITE_NAME)}">
<meta property="og:type" content="{'article' if kind == 'post' else 'website'}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{abs_url}">
<meta name="twitter:card" content="summary">
{extra_head}{font_preloads(*fonts)}
<style>{site_css()}</style>
</head>
<body>
{dragon_symbol()}
<header class="site-head">
<a class="mark" href="/" aria-label="Home">{DRAGON_USE}</a>
<nav><a href="/essays/">essays</a></nav>
</header>
<main>
{body}
</main>
<footer class="site-foot">
<span>{esc(AUTHOR)}</span>
<a href="/feed.xml">feed</a>
<a href="https://github.com/{REPO}">source</a>
</footer>
<script>{site_js()}</script>
</body>
</html>
"""


def render_post(doc: Doc) -> str:
    sep = '<span class="sep">·</span>'
    meta = [f'Published <time datetime="{doc.date.isoformat()}">{fmt_date(doc.date)}</time>']
    if doc.updated and doc.updated != doc.date:
        meta.append(f'updated <time datetime="{doc.updated.isoformat()}">{fmt_date(doc.updated)}</time>')
    meta.append(f"{doc.minutes} min read")
    meta.append(f'<a href="https://github.com/{REPO}/commits/main/posts/{doc.slug}.md">history</a>')
    if doc.canonical:
        label = "on LessWrong" if "lesswrong.com" in doc.canonical else "original"
        meta.append(f'<a href="{esc(doc.canonical)}">{label}</a>')
    body = f"""<article>
<header class="post-head">
<h1>{doc.title_html}</h1>
<p class="post-meta">{sep.join(f'<span class="mi">{m}</span>' for m in meta)}</p>
</header>
{doc.body_html}
</article>"""
    extra = (f'<meta property="article:published_time" content="{doc.date.isoformat()}">'
             + (f'<meta property="article:modified_time" content="{doc.updated.isoformat()}">' if doc.updated else ""))
    fonts = ("Regular", "SemiBold", "Italic") + (("InitialsF1", "InitialsF2") if doc.has_dropcap else ())
    return page_shell(title=plain(doc.title_html), description=plain(smarten(doc.description)), body=body,
                      url=doc.url, kind="post", extra_head=extra, fonts=fonts)


def render_page(doc: Doc) -> str:
    body = f"""<article>
<header class="post-head"><h1>{doc.title_html}</h1></header>
{doc.body_html}
</article>"""
    fonts = ("Regular", "SemiBold") + (("InitialsF1", "InitialsF2") if doc.has_dropcap else ())
    return page_shell(title=plain(doc.title_html), description=plain(smarten(doc.description)), body=body,
                      url=doc.url, fonts=fonts)


def render_home(doc: Doc) -> str:
    photo = ""
    if doc.meta.get("photo"):
        rel = str(doc.meta["photo"]).removeprefix("/assets/")
        rel = re.sub(r"\.(webp|avif)$", "", rel)
        src = next((p for p in (SRC_ASSETS / Path(rel).parent).glob(Path(rel).stem + ".*")), None)
        if src:
            info = encode_image(src.relative_to(SRC_ASSETS).as_posix(), max_width=320)
            if info:
                photo = (f'<picture><source type="image/avif" srcset="{info["avif"]}">'
                         f'<img src="{info["webp"]}" width="{info["w"]}" height="{info["h"]}" '
                         f'alt="{esc(str(doc.meta.get("photo_alt", AUTHOR)))}" fetchpriority="high"></picture>')
        else:
            warn(f"home photo not found under src-assets: {rel}")
    links = "".join(f'<li><a href="{esc(l["href"])}">{esc(l["text"])}</a></li>' for l in doc.meta.get("links", []))
    intro = smarten(str(doc.meta.get("intro", "")))
    body = f"""<section class="home">
{photo}
<h1 class="name">{doc.title_html}</h1>
<p class="intro">{intro}</p>
<nav><ul>{links}</ul></nav>
</section>
<section class="home-body">
{doc.body_html}
</section>"""
    return page_shell(title=plain(doc.title_html), description=plain(smarten(doc.description)), body=body, url="/",
                      fonts=("Regular", "Italic"))


def render_index(posts: list[Doc]) -> str:
    items = "".join(
        f'<li><a href="{p.url}">{p.title_html}</a>'
        f'<time datetime="{p.date.isoformat()}">{fmt_date(p.date, short=True)}</time></li>'
        for p in posts
    )
    body = f"""<section class="essays-index">
<h1>Essays</h1>
<ol class="essays" reversed>{items}</ol>
</section>"""
    return page_shell(title="Essays", description=f"Essays by {AUTHOR}.", body=body, url="/essays/",
                      fonts=("Regular", "SemiBold", "Italic"))


def render_404() -> str:
    body = f"""<section class="notfound">
{DRAGON_USE}
<h1>Not found</h1>
<p>There is nothing here. Try the <a href="/">home page</a> or the <a href="/essays/">essays</a>.</p>
</section>"""
    return page_shell(title="Not found", description="Page not found.", body=body, url="/404.html")


def render_proof() -> str:
    paras = "".join(
        f'<p><span class="dropcap" data-l="{c}">{c}</span>{c.lower()}ere is a paragraph that begins with the letter '
        f'{c}, long enough to wrap around the ornate initial and show how the baseline of the second and third '
        f'lines sits against it, with a little more text to be safe.</p>'
        for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    )
    body = f'<article><header class="post-head"><h1>Dropcap proof</h1></header>{paras}</article>'
    return page_shell(title="Dropcap proof", description="All 26 initials.", body=body, url="/_proof/dropcaps/",
                      fonts=("Regular", "InitialsF1", "InitialsF2"))


def absolutize(html_text: str) -> str:
    """Feed-ready HTML: absolute URLs, and no preview data attributes (they only feed popup.js)."""
    html_text = re.sub(r'(href|src|srcset)="/(?!/)', rf'\1="{SITE_URL}/', html_text)
    return re.sub(r""" data-(?:preview|title|desc|host)=(?:"[^"]*"|'[^']*')""", "", html_text)


def render_feed(posts: list[Doc]) -> bytes:
    ET.register_namespace("", "http://www.w3.org/2005/Atom")
    ns = "{http://www.w3.org/2005/Atom}"
    feed = ET.Element(ns + "feed")
    ET.SubElement(feed, ns + "title").text = SITE_NAME
    ET.SubElement(feed, ns + "subtitle").text = f"Essays by {AUTHOR}"
    ET.SubElement(feed, ns + "id").text = SITE_URL + "/"
    ET.SubElement(feed, ns + "link", href=SITE_URL + "/")
    ET.SubElement(feed, ns + "link", href=SITE_URL + "/feed.xml", rel="self")
    author = ET.SubElement(feed, ns + "author")
    ET.SubElement(author, ns + "name").text = AUTHOR
    latest = max((p.updated or p.date for p in posts), default=dt.date.today())
    ET.SubElement(feed, ns + "updated").text = f"{latest.isoformat()}T00:00:00Z"
    for p in posts:
        e = ET.SubElement(feed, ns + "entry")
        ET.SubElement(e, ns + "title").text = plain(p.title_html)
        ET.SubElement(e, ns + "id").text = SITE_URL + p.url
        ET.SubElement(e, ns + "link", href=SITE_URL + p.url)
        ET.SubElement(e, ns + "published").text = f"{p.date.isoformat()}T00:00:00Z"
        ET.SubElement(e, ns + "updated").text = f"{(p.updated or p.date).isoformat()}T00:00:00Z"
        ET.SubElement(e, ns + "summary").text = plain(smarten(p.description))
        c = ET.SubElement(e, ns + "content", type="html")
        c.text = absolutize(p.body_html)
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)


def render_sitemap(docs: list[Doc]) -> str:
    urls = "".join(
        f"<url><loc>{SITE_URL}{d.url}</loc>"
        + (f"<lastmod>{(d.updated or d.date).isoformat()}</lastmod>" if (d.updated or d.date) else "")
        + "</url>"
        for d in docs
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'


# ----------------------------------------------------------------------------- pipeline

def write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not path.exists() or path.read_bytes() != content:
        path.write_bytes(content)
    written.add(path)


def copy_static() -> None:
    for src in STATIC.rglob("*"):
        if src.is_dir() or src.name in ("style.css", "popup.js", "dragon.svg", "README.md"):
            continue
        dest = OUT / src.relative_to(STATIC)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.read_bytes() != src.read_bytes():
            shutil.copyfile(src, dest)
        written.add(dest)


def prune() -> None:
    for p in sorted(OUT.rglob("*"), reverse=True):
        if p.is_file() and p not in written:
            p.unlink()
            print(f"  pruned {p.relative_to(OUT)}")
        elif p.is_dir() and not any(p.iterdir()):
            p.rmdir()


def check(posts: list[Doc], pages: list[Doc]) -> None:
    emitted = {d.url for d in posts + pages} | {"/essays/", "/feed.xml", "/sitemap.xml", "/404.html"}
    for d in posts + pages:
        soup = BeautifulSoup(d.body_html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("#") or href.startswith("mailto:"):
                continue
            if is_external(href):
                if "arc" in a.get("class", []) or "web.archive.org" in href:
                    continue
                e = archive().get(href)
                if not e or e.get("status") != "ok":
                    warn(f"{d.slug}: external link not archived: {href}")
                elif not e.get("local") or not (STATIC / "archive" / e["local"].removeprefix("/archive/")).exists():
                    warn(f"{d.slug}: no local archive copy (only Wayback): {href}")
            elif href.startswith("/"):
                path = href.split("#")[0]
                if path not in emitted and not (OUT / path.lstrip("/")).exists():
                    warn(f"{d.slug}: internal link does not resolve: {href}")
        if "{:" in d.text:
            warn(f"{d.slug}: literal '{{:' in output text (attr_list leak?)")
        if d.kind == "post" and d.dropcap and not d.has_dropcap:
            warn(f"{d.slug}: no dropcap emitted (first paragraph does not start with A-Z)")
        if "TODO" in d.description:
            warn(f"{d.slug}: description still marked TODO")


def build(include_drafts: bool, proof: bool, do_check: bool) -> None:
    OUT.mkdir(exist_ok=True)
    posts, pages = collect(include_drafts)
    docs_by_url.update({d.url: d for d in posts + pages})
    for d in posts + pages:
        d.title_html = smarten(d.title)
        d.body_html = render_markdown(d.body_md)
        postprocess(d)
    for p in posts:
        write(p.out_path, render_post(p))
    for pg in pages:
        if pg.template == "home":
            write(pg.out_path, render_home(pg))
        else:
            write(pg.out_path, render_page(pg))
    write(OUT / "essays" / "index.html", render_index(posts))
    write(OUT / "404.html", render_404())
    write(OUT / "feed.xml", render_feed(posts))
    write(OUT / "sitemap.xml", render_sitemap(posts + [pg for pg in pages]))
    if proof:
        write(OUT / "_proof" / "dropcaps" / "index.html", render_proof())
    copy_static()
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    write(MANIFEST_PATH, json.dumps(dict(sorted(manifest().items())), indent=2) + "\n")
    prune()
    if do_check:
        check(posts, pages)
    print(f"built {len(posts)} posts, {len(pages)} pages -> {OUT.relative_to(ROOT)}/"
          + (f" ({len(warnings)} warnings)" if warnings else ""))


def serve(port: int) -> None:
    import http.server
    import functools

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
    handler.extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                              ".woff2": "font/woff2", ".avif": "image/avif", ".webp": "image/webp",
                              ".xml": "application/xml"}
    print(f"serving {OUT} at http://localhost:{port}/")
    http.server.ThreadingHTTPServer(("", port), handler).serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drafts", action="store_true", help="include draft posts")
    ap.add_argument("--serve", nargs="?", const=8000, type=int, metavar="PORT", help="build, then serve docs/")
    ap.add_argument("--check", action="store_true", help="validate links, archives, and frontmatter")
    ap.add_argument("--proof", action="store_true", help="also write docs/_proof/dropcaps/")
    a = ap.parse_args()
    build(a.drafts, a.proof, a.check)
    if a.serve:
        serve(a.serve)
    elif a.check and warnings:
        sys.exit(1)


if __name__ == "__main__":
    main()
