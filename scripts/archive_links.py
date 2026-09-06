#!/usr/bin/env python3
"""Archive every external link in posts/ and pages/ so the site can serve its own copies.

Modelled on gwern.net's local link archiving: each page is snapshotted with SingleFile
(one self-contained HTML file, scripts stripped, assets inlined) into

    static/archive/<host>/<sha1 of url>.html      served at /archive/<host>/<sha1>.html

PDFs and other non-HTML targets are saved verbatim with their own extension. A robots
meta tag and a small banner naming the original URL are added to each HTML snapshot;
robots.txt keeps crawlers out of /archive/. The Wayback Machine is asked for a snapshot
too, as an off-site backup.

Writes archive.json: {url: {"status": "ok"|"failed", "local": "/archive/...",
"fetched": "YYYY-MM-DD", "archived": wayback_url, "timestamp": "YYYYMMDDhhmmss",
"checked": "YYYY-MM-DD", "error": "..."}}. build.py reads it to add the small "a"
archive mark after each external link, preferring the local copy.

Needs node and pnpm (for `pnpm dlx single-file-cli`) and a Chromium/Chrome binary.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "archive.json"
STORE = ROOT / "static" / "archive"
URL_PREFIX = "/archive"
OWN_HOSTS = {"drakemorrison.net", "www.drakemorrison.net"}
UA = "drakemorrison.net link archiver (drake.morrison@hey.com)"
BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/128.0.0.0 Safari/537.36")  # for plain downloads; SingleFile uses the browser's own
BROWSERS = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave", "chrome")
SNAPSHOT_TIMEOUT = 240
LINK_RE = re.compile(r"\]\((https?://[^)\s]+)|<(https?://[^>\s]+)>|(?<![\](])(?<!\w)(https?://[^\s)<>\"']+)")
ROBOTS_META = '<meta name="robots" content="noindex,nofollow,noarchive">'
BANNER_STYLE = ("all:initial;display:block;box-sizing:border-box;width:100%;padding:0.6em 1em;"
                "background:#f3ece3;color:#100f0d;border-bottom:1px solid #e4e1da;"
                "font:15px/1.4 Georgia,'Times New Roman',serif;position:relative;z-index:2147483647")
BANNER_LINK = "color:#c7421c;text-decoration:underline"


# ----------------------------------------------------------------------------- sources

def collect_urls() -> list[str]:
    urls: set[str] = set()
    for md in list((ROOT / "posts").glob("*.md")) + list((ROOT / "pages").glob("*.md")):
        for m in LINK_RE.finditer(md.read_text(encoding="utf-8")):
            url = next(g for g in m.groups() if g)
            url = url.rstrip(".,;:!?")
            url = urllib.parse.urldefrag(url).url
            host = urllib.parse.urlparse(url).hostname or ""
            if host in OWN_HOSTS or host.endswith("archive.org"):
                continue
            urls.add(url)
    return sorted(urls)


def local_stem(url: str) -> tuple[str, str]:
    """(host directory, sha1 filename stem) for a URL; the hash sidesteps escaping and deep paths."""
    host = urllib.parse.urlparse(url).hostname or "unknown"
    return host, hashlib.sha1(url.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------- http

def get(url: str, timeout: int = 90, ua: str = UA) -> tuple[int, dict, bytes, str]:
    """GET following redirects; returns (status, headers, body, final_url)."""
    req = urllib.request.Request(url, headers={"user-agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), b"", e.geturl() or url


def content_type(url: str) -> str:
    req = urllib.request.Request(url, method="HEAD", headers={"user-agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    except Exception:  # noqa: BLE001 - HEAD is a hint only; fall through to the page fetch
        return ""


# ----------------------------------------------------------------------------- local snapshot

def find_browser() -> str | None:
    if os.environ.get("ARCHIVE_BROWSER"):
        return os.environ["ARCHIVE_BROWSER"]
    for name in BROWSERS:
        if p := shutil.which(name):
            return p
    return None


def banner(url: str, today: str) -> str:
    when = dt.date.fromisoformat(today).strftime("%-d %B %Y")
    u = html.escape(url, quote=True)
    return (f'<div id="drakemorrison-archive-banner" style="{BANNER_STYLE}">'
            f'Archived copy of <a href="{u}" style="{BANNER_LINK}">{u}</a>, saved {when} '
            f'for <a href="https://drakemorrison.net/" style="{BANNER_LINK}">drakemorrison.net</a>. '
            f'<a href="{u}" style="{BANNER_LINK}">Open the live page</a>.</div>')


def stamp(doc: str, url: str, today: str) -> str:
    """Strip scripts, add the robots meta tag and the provenance banner to a SingleFile snapshot."""
    doc = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", doc, flags=re.I | re.S)
    # SingleFile drops <head> when it can; the meta still lands in the implicit head after <html>
    doc, n = re.subn(r"(<head[^>]*>)", lambda m: m.group(1) + ROBOTS_META, doc, count=1, flags=re.I)
    if not n:
        doc, n = re.subn(r"(<html[^>]*>(?:\s*<!--.*?-->)?)", lambda m: m.group(1) + ROBOTS_META, doc,
                         count=1, flags=re.I | re.S)
    if not n:
        doc = ROBOTS_META + doc
    doc, n = re.subn(r"(<body[^>]*>)", lambda m: m.group(1) + banner(url, today), doc, count=1, flags=re.I)
    if not n:
        doc = banner(url, today) + doc
    return doc


CHALLENGE_RE = re.compile(r"<title>[^<]*(checking your browser|just a moment|attention required|access denied|"
                          r"verify you are human|making sure you're not a bot|are you a robot)", re.I)


def single_file(url: str, browser: str, allow_scripts: bool) -> str:
    with tempfile.TemporaryDirectory(prefix="archive-") as tmp:
        out = Path(tmp) / "page.html"
        cmd = ["pnpm", "dlx", "single-file-cli",
               f"--browser-executable-path={browser}",
               "--browser-arg=--no-sandbox",
               "--block-videos=true", "--block-audios=true", "--remove-frames=true",
               "--remove-hidden-elements=true", "--remove-unused-styles=true",
               "--max-resource-size-enabled=true", "--max-resource-size=8"]
        if allow_scripts:
            # let a bot-check interstitial run and resolve before capturing; scripts are still
            # not kept in the saved file
            cmd += ["--block-scripts=false", "--browser-wait-delay=8000"]
        r = subprocess.run(cmd + [url, str(out)], capture_output=True, text=True, timeout=SNAPSHOT_TIMEOUT)
        if not out.exists() or out.stat().st_size == 0:
            err = (r.stderr or r.stdout).strip().splitlines()
            raise RuntimeError("single-file: " + (err[-1] if err else f"exit {r.returncode}"))
        return out.read_text(encoding="utf-8", errors="replace")


def snapshot_html(url: str, dest: Path, browser: str, today: str) -> None:
    doc = single_file(url, browser, allow_scripts=False)
    if CHALLENGE_RE.search(doc[:4000]):
        doc = single_file(url, browser, allow_scripts=True)
        if CHALLENGE_RE.search(doc[:4000]):
            raise RuntimeError("blocked by a bot check")
    if "<html" not in doc[:4000].lower():
        raise RuntimeError("single-file produced no HTML document")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(stamp(doc, url, today), encoding="utf-8")


def snapshot_file(url: str, dest: Path) -> None:
    status, _, body, _ = get(url, timeout=120, ua=BROWSER_UA)
    if status != 200 or not body:
        raise RuntimeError(f"download returned {status}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)


EXT_FOR = {"application/pdf": ".pdf", "text/plain": ".txt", "image/png": ".png", "image/jpeg": ".jpg",
           "image/gif": ".gif", "image/webp": ".webp", "image/svg+xml": ".svg", "application/json": ".json"}


def snapshot(url: str, browser: str | None, today: str) -> str:
    """Save a local copy; returns the site-relative URL of the copy."""
    host, stem = local_stem(url)
    ctype = content_type(url)
    ext = EXT_FOR.get(ctype)
    if ext is None and re.search(r"\.pdf($|[?#])", url, re.I):
        ext = ".pdf"
    if ext:
        dest = STORE / host / (stem + ext)
        snapshot_file(url, dest)
    else:
        if not browser:
            raise RuntimeError("no Chromium/Chrome found; set ARCHIVE_BROWSER")
        dest = STORE / host / (stem + ".html")
        snapshot_html(url, dest, browser, today)
    return f"{URL_PREFIX}/{host}/{dest.name}"


def remove_local(entry: dict) -> None:
    local = entry.get("local")
    if not local:
        return
    p = STORE / Path(local).relative_to(URL_PREFIX)
    if p.exists():
        p.unlink()
        if p.parent != STORE and not any(p.parent.iterdir()):
            p.parent.rmdir()


# ----------------------------------------------------------------------------- wayback

def available(url: str) -> tuple[str, str] | None:
    q = "https://archive.org/wayback/available?url=" + urllib.parse.quote(url, safe="")
    status, _, body, _ = get(q, timeout=30)
    if status != 200:
        return None
    snap = json.loads(body).get("archived_snapshots", {}).get("closest")
    if not snap or not snap.get("available"):
        return None
    ts = snap["timestamp"]
    return f"https://web.archive.org/web/{ts}/{url}", ts


def save(url: str) -> tuple[str, str] | None:
    status, headers, _, final = get("https://web.archive.org/save/" + url)
    if status in (429, 502, 503, 504):
        raise RuntimeError(f"save returned {status}")
    # the save endpoint 302s to /web/<timestamp>/<url>; urlopen follows it, so read the final URL
    loc = " ".join([final, headers.get("Content-Location", ""), headers.get("Location", "")])
    m = re.search(r"/web/(\d{14})/", loc)
    if m:
        return f"https://web.archive.org/web/{m.group(1)}/{url}", m.group(1)
    time.sleep(10)
    return available(url)


def wayback(url: str, delay: float) -> tuple[str, str] | None:
    found = available(url)
    if not found:
        found = save(url)
        time.sleep(delay)
    return found


# ----------------------------------------------------------------------------- main

def write_json(data: dict) -> None:
    ARCHIVE.write_text(json.dumps(dict(sorted(data.items())), indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-snapshot every URL")
    ap.add_argument("--no-wayback", action="store_true", help="skip the Wayback Machine backup")
    ap.add_argument("--delay", type=float, default=6, help="seconds between Wayback save requests")
    ap.add_argument("--retry-days", type=int, default=7, help="retry failed entries older than this")
    ap.add_argument("--only", metavar="SUBSTR", help="limit to URLs containing this text (implies --force)")
    a = ap.parse_args()
    if a.only:
        a.force = True

    data: dict = json.loads(ARCHIVE.read_text()) if ARCHIVE.exists() else {}
    today = dt.date.today().isoformat()
    urls = collect_urls()
    browser = find_browser()
    todo = []
    for u in urls:
        if a.only and a.only not in u:
            continue
        e = data.get(u)
        local_ok = bool(e and e.get("local") and (STORE / Path(e["local"]).relative_to(URL_PREFIX)).exists())
        if a.force or e is None or not local_ok:
            if e and not local_ok and e.get("status") == "failed":
                checked = dt.date.fromisoformat(e.get("checked", "1970-01-01"))
                if (dt.date.today() - checked).days < a.retry_days:
                    continue
            todo.append(u)
    print(f"{len(urls)} external urls, {len(todo)} to snapshot (browser: {browser or 'none'})")
    if a.dry_run:
        for u in todo:
            print("  ", u)
        return

    for u in todo:
        prev = data.get(u) or {}
        entry = {k: v for k, v in prev.items() if k in ("archived", "timestamp")}
        entry.update(status="failed", checked=today)
        try:
            remove_local(prev)
            entry["local"] = snapshot(u, browser, today)
            entry["fetched"] = today
            entry["status"] = "ok"
            print(f"saved    {u} -> {entry['local']}")
        except Exception as ex:  # noqa: BLE001
            entry["error"] = str(ex)[:200]
            print(f"failed   {u}: {ex}")
        if not a.no_wayback and "archived" not in entry:
            try:
                if found := wayback(u, a.delay):
                    entry["archived"], entry["timestamp"] = found
                    if entry["status"] != "ok":
                        entry["status"] = "ok"  # off-site copy only; --check will still ask for a local one
                    print(f"wayback  {u} -> {found[0]}")
            except Exception as ex:  # noqa: BLE001
                print(f"wayback  {u}: {ex}")
        data[u] = entry
        write_json(data)

    # drop entries and snapshots whose URL no longer appears anywhere
    stale = [u for u in data if u not in urls]
    for u in stale:
        remove_local(data.pop(u))
    write_json(data)
    have = sum(1 for e in data.values() if e.get("local"))
    print(f"wrote archive.json ({len(data)} entries, {have} local copies, {len(stale)} stale removed)")


if __name__ == "__main__":
    main()
