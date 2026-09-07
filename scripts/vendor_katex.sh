#!/usr/bin/env sh
# Vendor KaTeX (MIT): katex.min.js for build-time rendering (scripts/vendor/katex/),
# the woff2 fonts (static/fonts/katex/), and a CSS trimmed to woff2-only sources that
# build.py inlines into pages with math (static/katex.css).
#
#   scripts/vendor_katex.sh [version]
set -eu
cd "$(dirname "$0")/.."
ver=${1:-0.18.5}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
(cd "$tmp" && npm pack "katex@$ver" --silent >/dev/null && tar xzf katex-*.tgz)
mkdir -p scripts/vendor/katex static/fonts/katex
rm -f static/fonts/katex/*.woff2
cp "$tmp/package/dist/katex.min.js" "$tmp/package/LICENSE" scripts/vendor/katex/
cp "$tmp"/package/dist/fonts/*.woff2 static/fonts/katex/
sed -E 's#,url\(fonts/[^)]*\.(woff|ttf)\) format\("[^"]*"\)##g; s#url\(fonts/#url(/fonts/katex/#g' \
  "$tmp/package/dist/katex.min.css" > static/katex.css
echo "$ver" > scripts/vendor/katex/VERSION
echo "vendored katex $ver"
