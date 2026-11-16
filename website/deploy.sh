#!/usr/bin/env bash
# Publish website/ to https://nettap.dev on nginx-local (192.168.1.24, ssh alias, root, key auth).
# Usage: website/deploy.sh             build, upload a new release, make it live and verify; any failure rolls back
#        website/deploy.sh --rollback  serve the previous release again
set -euo pipefail
cd "$(dirname "$0")"
HOST=nginx-local
BASE=/var/www/nettap.dev

remote() { ssh -o BatchMode=yes "$HOST" "bash -s -- $*" < deploy-remote.sh; }

if [ "${1:-}" = --rollback ]; then
  remote rollback
  exit
fi
[ $# -eq 0 ] || { echo "usage: $0 [--rollback]" >&2; exit 2; }

REL="$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short HEAD)"
[ -z "$(git status --porcelain -- .)" ] || REL="$REL-dirty"
./build.sh "$REL"

echo "→ Uploading release $REL"
ssh -o BatchMode=yes "$HOST" "install -d -m 755 $BASE $BASE/releases"
rsync -rlt --delete --exclude .DS_Store dist/ "$HOST:$BASE/releases/$REL/"
rsync -t nginx/nettap.dev.conf "$HOST:/root/nettap.dev.conf.new"
remote deploy "$REL"

echo "→ From this Mac through public DNS"
IP="$(dig +short nettap.dev @1.1.1.1 | tail -n 1)"
curl -fsS -o /dev/null -w "   ✓ https://nettap.dev/ %{http_code} via $IP\n" --resolve "nettap.dev:443:$IP" https://nettap.dev/
