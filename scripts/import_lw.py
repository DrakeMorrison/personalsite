#!/usr/bin/env python3
"""Import LessWrong posts into posts/<slug>.md (one-time tool, idempotent).

  scripts/import_lw.py --list
  scripts/import_lw.py [--force] [--rename lw-slug=new-slug ...] lw-slug ...
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "posts"
SRC_ASSETS = ROOT / "src-assets"
GRAPHQL = "https://www.lesswrong.com/graphql"
DEFAULT_USER = "6NBDkGWcCxvLgYHJE"  # drake-morrison
TZ = ZoneInfo("America/Los_Angeles")
UA = "drakemorrison.net importer (drake.morrison@hey.com)"


def gql(query: str) -> dict:
    req = urllib.request.Request(
        GRAPHQL,
        data=json.dumps({"query": query}).encode(),
        headers={"content-type": "application/json", "user-agent": UA},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    if "errors" in data:
        raise SystemExit(f"GraphQL error: {data['errors'][0]['message']}")
    return data["data"]


def list_posts(user_id: str) -> list[dict]:
    q = ('{ posts(input:{terms:{view:"userPosts", userId:"%s", limit:200}}) '
         '{ results { _id title slug postedAt } } }' % user_id)
    return gql(q)["posts"]["results"]


def fetch_post(post_id: str) -> dict:
    q = ('{ post(input:{selector:{_id:"%s"}}) { result { _id title postedAt modifiedAt '
         'pageUrl htmlBody contents { markdown } } } }' % post_id)
    return gql(q)["post"]["result"]


def clean_markdown(md: str) -> str:
    md = md.replace("\r\n", "\n").replace(" ", " ")
    lines = md.split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        if line.strip() == "":
            out.append("")
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if nxt.strip() == "":  # trailing "  " before a blank line is a LW artefact, not a <br>
            line = line.rstrip()
        out.append(line)
    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


def renumber_footnotes(md: str) -> str:
    defs = re.findall(r"^\[\^([^\]]+)\]:", md, flags=re.M)
    refs = re.findall(r"\[\^([^\]]+)\](?!:)", md)
    order: list[str] = []
    for ident in refs + defs:
        if ident not in order:
            order.append(ident)
    if all(i.isdigit() for i in order):
        return md
    mapping = {ident: str(n + 1) for n, ident in enumerate(order)}
    return re.sub(r"\[\^([^\]]+)\]", lambda m: f"[^{mapping.get(m.group(1), m.group(1))}]", md)


def sniff_ext(data: bytes, url: str) -> str:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").lower()
        return {"jpeg": ".jpg", "png": ".png", "gif": ".gif", "webp": ".webp"}.get(fmt, "." + fmt if fmt else ".bin")
    except Exception:
        m = re.search(r"\.(png|jpe?g|gif|webp|svg)(?:$|\?)", url, re.I)
        return "." + m.group(1).lower() if m else ".bin"


def download_images(md: str, slug: str) -> str:
    urls: list[str] = []
    md_img = re.compile(r'!\[([^\]]*)\]\((\S+?)(?:\s+"([^"]*)")?\)')
    html_img = re.compile(r'<img[^>]+src="([^"]+)"[^>]*>')
    for m in md_img.finditer(md):
        urls.append(m.group(2))
    for m in html_img.finditer(md):
        urls.append(m.group(1))
    if not urls:
        return md
    dest = SRC_ASSETS / slug
    dest.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    for n, url in enumerate(dict.fromkeys(urls), start=1):
        req = urllib.request.Request(url, headers={"user-agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        base = re.sub(r"[^a-z0-9]+", "-", Path(url.split("?")[0]).stem.lower()).strip("-")[:40] or "image"
        name = f"{n:02d}-{base}{sniff_ext(data, url)}"
        (dest / name).write_bytes(data)
        mapping[url] = f"/assets/{slug}/{name}"
        print(f"  image {url} -> src-assets/{slug}/{name}")
    md = md_img.sub(lambda m: f'![{m.group(1)}]({mapping[m.group(2)]}' + (f' "{m.group(3)}"' if m.group(3) else "") + ")", md)
    md = html_img.sub(lambda m: m.group(0).replace(m.group(1), mapping[m.group(1)]), md)
    return md


def first_sentence(md: str, limit: int = 160) -> str:
    text = re.sub(r"^\(.*?\)\s*", "", md.strip(), count=1, flags=re.S)  # skip a parenthetical preface
    text = re.sub(r"\[\^[^\]]+\]", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`#>]+", "", text)
    text = " ".join(text.split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    s = m.group(1) if m else text
    if len(s) > limit:
        s = s[: limit - 1].rsplit(" ", 1)[0] + "…"
    return s


def yaml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def write_post(post: dict, slug: str, force: bool) -> None:
    path = POSTS / f"{slug}.md"
    if path.exists() and not force:
        print(f"skip {path} (exists; use --force)")
        return
    md = clean_markdown(post["contents"]["markdown"] or "")
    md = renumber_footnotes(md)
    md = download_images(md, slug)
    posted = dt.datetime.fromisoformat(post["postedAt"].replace("Z", "+00:00")).astimezone(TZ).date()
    modified = dt.datetime.fromisoformat(post["modifiedAt"].replace("Z", "+00:00")).astimezone(TZ).date()
    fm = [
        "---",
        f"title: {yaml_str(post['title'])}",
        f"date: {posted.isoformat()}",
    ]
    if modified > posted:
        fm.append(f"updated: {modified.isoformat()}")
    fm += [
        f"description: {yaml_str(first_sentence(md))}  # TODO: edit",
        f"canonical: {post['pageUrl']}",
        f"lw_id: {post['_id']}",
        "draft: false",
        "---",
        "",
    ]
    POSTS.mkdir(exist_ok=True)
    path.write_text("\n".join(fm) + md, encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", default=DEFAULT_USER)
    ap.add_argument("--list", action="store_true", help="list the user's posts and exit")
    ap.add_argument("--force", action="store_true", help="overwrite existing posts/<slug>.md")
    ap.add_argument("--rename", action="append", default=[], metavar="LW=NEW", help="use NEW as the local slug")
    ap.add_argument("slugs", nargs="*", help="LessWrong slugs to import")
    a = ap.parse_args()

    posts = list_posts(a.user)
    if a.list or not a.slugs:
        for p in sorted(posts, key=lambda p: p["postedAt"], reverse=True):
            print(f"{p['postedAt'][:10]}  {p['_id']}  {p['slug']}  |  {p['title']}")
        return
    renames = dict(r.split("=", 1) for r in a.rename)
    by_slug = {p["slug"]: p for p in posts}
    for s in a.slugs:
        if s not in by_slug:
            sys.exit(f"no post with slug {s!r}; run --list")
        post = fetch_post(by_slug[s]["_id"])
        write_post(post, renames.get(s, s), a.force)


if __name__ == "__main__":
    main()
