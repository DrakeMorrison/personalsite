# drakemorrison.net

Personal site and essays. Markdown in, static HTML out, served by GitHub Pages from `docs/`.
No JavaScript, no external requests: fonts, images, and styles are all self-hosted.

## Layout

| Path | What |
| --- | --- |
| `posts/<slug>.md` | Essays. The filename is the URL: `/essays/<slug>/`. |
| `pages/<slug>.md` | Standalone pages: `/<slug>/`. `pages/index.md` is the home page. |
| `src-assets/<slug>/` | Image originals. Referenced from markdown as `/assets/<slug>/name.png`. |
| `static/` | Copied into `docs/` as-is (fonts, favicon, CNAME). `style.css` and `dragon.svg` are inlined. |
| `archive.json` | Wayback Machine snapshots for every external link. |
| `docs/` | Generated output. Committed, served. Do not edit by hand. |

## Writing a post

```markdown
---
title: "Plans are Not Promises"
date: 2026-04-14
updated: 2026-04-15            # optional
description: "One or two sentences for the index, feed, and link previews."
canonical: https://www.lesswrong.com/posts/...   # optional; shown as "on LessWrong"
draft: false                   # true hides it unless you build with --drafts
dropcap: true                  # optional; default true for posts
---

Body in markdown. Footnotes[^1], images, tables, and fenced code all work.
A `---` line becomes a dragon divider. A paragraph wrapped in (parentheses) is
rendered as an italic aside.

[^1]: Like this.
```

The first paragraph's first letter (A–Z) becomes an ornate initial. Images go in
`src-assets/<slug>/` and are encoded to AVIF and WebP at build time, with dimensions
baked in.

## Build

```sh
python3 build.py            # render into docs/
python3 build.py --serve    # and preview at http://localhost:8000/
python3 build.py --check    # warn on unarchived links, broken internal links, missing images
python3 scripts/archive_links.py   # snapshot new external links with the Wayback Machine
```

Then commit `docs/` along with the sources and push `main`. GitHub Pages serves `docs/`.

Needs Python 3 with `markdown`, `pyyaml`, `beautifulsoup4`, and `pillow`, plus
ImageMagick (`magick`) for image encoding.

## One-off tools

- `scripts/import_lw.py --list` / `scripts/import_lw.py <lw-slug> ...`: pull posts from
  LessWrong into `posts/` (see `--rename` for shorter slugs).
- `scripts/build_fonts.sh`: rebuild the subset WOFF2 fonts in `static/fonts/`.

## Design notes

Warm off-white page, near-black ink, and one accent: links are "rubricated" in an
ember red (`--fire`). Body text is EB Garamond; initials are EB Garamond Initials
(letter in ink, embellishment in fire). The dragon mark is the Noto Emoji dragon.
Every external link carries a small superscript `a` pointing at its archived copy.
