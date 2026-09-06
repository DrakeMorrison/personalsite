#!/usr/bin/env bash
# One-off: build the subset WOFF2 fonts in static/fonts/.
#   EB Garamond Regular/Italic/SemiBold  <- CTAN ebgaramond package (OFL)
#   EB Garamond Initials F1/F2 (A-Z)     <- turntrout.com's full-alphabet build (OFL derivative)
# Needs python3 + network. Creates a throwaway venv with fonttools+brotli in $WORK.
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
OUTDIR="$HERE/static/fonts"
WORK=${WORK:-$(mktemp -d)}
mkdir -p "$OUTDIR" "$WORK"
cd "$WORK"

if [ ! -x fontvenv/bin/pyftsubset ]; then
  python3 -m venv fontvenv
  fontvenv/bin/pip -q install fonttools brotli
fi
SUBSET=fontvenv/bin/pyftsubset

[ -f ebgaramond.zip ] || curl -L -o ebgaramond.zip https://mirrors.ctan.org/fonts/ebgaramond.zip
unzip -oq ebgaramond.zip 'ebgaramond/opentype/EBGaramond-Regular.otf' \
  'ebgaramond/opentype/EBGaramond-Italic.otf' 'ebgaramond/opentype/EBGaramond-SemiBold.otf' \
  'ebgaramond/doc/OFL.txt'
TT=https://raw.githubusercontent.com/alexander-turner/TurnTrout.com/main/quartz/static/styles/fonts/EBGaramond
for f in F1 F2; do
  [ -f "tt_Initials$f.woff2" ] || curl -L -o "tt_Initials$f.woff2" "$TT/EBGaramond-Initials$f.woff2"
done

LATIN='U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD'
for face in Regular Italic SemiBold; do
  "$SUBSET" "ebgaramond/opentype/EBGaramond-$face.otf" --flavor=woff2 --unicodes="$LATIN" \
    --layout-features+=smcp,c2sc,onum,lnum,pnum,tnum --name-IDs='*' \
    --output-file="$OUTDIR/EBGaramond-$face.woff2"
done
for f in F1 F2; do
  "$SUBSET" "tt_Initials$f.woff2" --flavor=woff2 --unicodes='U+0041-005A' --name-IDs='*' \
    --output-file="$OUTDIR/EBGaramond-Initials$f.woff2"
done
cp ebgaramond/doc/OFL.txt "$OUTDIR/OFL.txt"
ls -l "$OUTDIR"
du -ch "$OUTDIR"/*.woff2 | tail -1
