#!/usr/bin/env bash
# Build website/site into website/dist: bundle and minify the 3D hero, minify the CSS, stamp the release.
# Usage: website/build.sh [release-name]   (deploy.sh passes one; the default is "dev")
set -euo pipefail
cd "$(dirname "$0")"
REL="${1:-dev}"
MODULES="$(cd .. && pwd)/web/node_modules"
ESBUILD="$MODULES/.bin/esbuild"
[ -x "$ESBUILD" ] || { echo "esbuild not found. Run: cd web && npm ci" >&2; exit 1; }

rm -rf dist
cp -R site dist
python3 build-features.py dist
rm dist/hero-lens.js  # bundled into hero.js
# three.js comes from web's installed copy (three/webgpu, three/tsl, three/addons via its exports map).
NODE_PATH="$MODULES" "$ESBUILD" site/hero.js --bundle --minify --format=esm --target=es2022 \
  --outfile=dist/hero.js --log-level=warning
"$ESBUILD" site/tokens.css site/site.css site/features.css --minify --outdir=dist --log-level=warning

perl -pi -e "s/(name=\"nettap-release\" content=)\"dev\"/\$1\"$REL\"/" dist/*.html
for f in dist/*.html; do
  grep -q "name=\"nettap-release\" content=\"$REL\"" "$f" || { echo "release stamp missing in $f" >&2; exit 1; }
done

# The CSP allows exactly one inline script by hash; every page must carry that same line.
inline="$(perl -0ne 'print "$1\n" while m{<script>(.*?)</script>}gs' dist/*.html | sort -u)"
[ "$(printf '%s\n' "$inline" | wc -l | tr -d ' ')" = 1 ] || { echo "expected one distinct inline script, got: $inline" >&2; exit 1; }
hash="sha256-$(printf '%s' "$inline" | openssl dgst -sha256 -binary | base64)"
grep -q "'$hash'" nginx/nettap.dev.conf || { echo "CSP hash out of date: put '$hash' in nginx/nettap.dev.conf" >&2; exit 1; }

echo "Built dist/ ($REL): hero.js $(wc -c < dist/hero.js | tr -d ' ') bytes, $(gzip -9c dist/hero.js | wc -c | tr -d ' ') gzipped"
