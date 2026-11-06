#!/usr/bin/env bash
# Deploy NET-166, data sizes in decimal units (1 GB = 1,000,000,000 bytes), then check on the device:
#   - the disk figures are bytes / 10^9 of the daemon's own byte counts, and the total matches df
#   - the index list carries exact byte counts (whole numbers, or null when OpenSearch sent none)
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-decimal-units.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="main"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

api() {  # api <path> <python expression over the reply `d`>: GET a daemon route with the token
    # The path and expression are always literals from this script. The token is read inside the
    # container, inside fetch(): it, the headers and the request are gone before the eval runs
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.error, urllib.request
def fetch(path):
    headers = {'X-NetTap-Daemon-Token': open('/run/nettap-auth/daemon-token').read().strip()}
    req = urllib.request.Request('http://localhost:8880' + path, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return json.load(r)
    except (urllib.error.URLError, ValueError):
        return {}
d = fetch(sys.argv[1])
del fetch
print(eval(sys.argv[2]))" "$1" "$2" 2>&1 | tail -n 1
}

echo "=== Deploy: data sizes in decimal units (NET-166) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build and recreate the daemon and the web container..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web; then
    echo "   ✗ Could not recreate the containers"
    exit 1
fi
for svc in nettap-storage-daemon nettap-web; do
    STATUS="unknown"
    for _ in $(seq 1 36); do
        STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' "$svc" 2>/dev/null || echo "unknown")
        [ "$STATUS" = "healthy" ] && break
        sleep 5
    done
    if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
    check "$svc health" "$rc" "$STATUS"
done
echo ""

echo "→ Step 3: Disk figures are decimal GB..."
DISK=$(api /api/storage/status "'%s B total = %s GB, %s B used = %s GB, %s B free = %s GB' % (d.get('disk_total_bytes'), d.get('disk_total_gb'), d.get('disk_used_bytes'), d.get('disk_used_gb'), d.get('disk_free_bytes'), d.get('disk_free_gb'))")
echo "   $DISK"
VERDICT=$(api /api/storage/status "'OK' if all(isinstance(d.get(k + '_bytes'), int) and d.get(k + '_gb') == round(d[k + '_bytes'] / 1e9, 2) for k in ('disk_total', 'disk_used', 'disk_free')) else 'BAD'")
if [ "$VERDICT" = "OK" ]; then rc=0; else rc=1; fi
check "each *_gb is its byte count / 1,000,000,000" "$rc" "$VERDICT"
DAEMON_TOTAL=$(api /api/storage/status "d.get('disk_total_bytes')")
DF_LINE=$(df -B1 --output=size,target 2>/dev/null | awk -v t="$DAEMON_TOTAL" '$1 == t {print $2; exit}')
if [ -n "$DF_LINE" ]; then rc=0; else rc=1; fi
check "df on the host has a filesystem of exactly that many bytes" "$rc" "${DF_LINE:-none of $(df -B1 --output=size | tail -n +2 | tr '\n' ' ')}"
echo ""

echo "→ Step 4: Index sizes are exact bytes..."
VERDICT=$(api /api/opensearch/indices "(lambda xs: 'OK %d indices, %d without a size' % (len(xs), sum(1 for i in xs if i.get('store_size') is None)) if xs and all((i.get(k) is None or (isinstance(i.get(k), int) and i[k] >= 0)) for i in xs for k in ('store_size', 'pri_store_size')) and all(i['pri_store_size'] <= i['store_size'] for i in xs if i.get('store_size') is not None and i.get('pri_store_size') is not None) else 'BAD')(d.get('indices', []))")
case "$VERDICT" in OK*) rc=0 ;; *) rc=1 ;; esac
check "every size is a whole number of bytes or null, and primary <= total" "$rc" "$VERDICT"
BIGGEST=$(api /api/opensearch/indices "(lambda xs: '%s: %d bytes = %.1f GB on the Infrastructure page' % (xs[0]['index'], xs[0]['store_size'], xs[0]['store_size'] / 1e9) if xs else 'no sized index')(sorted([i for i in d.get('indices', []) if isinstance(i.get('store_size'), int)], key=lambda i: -i['store_size']))")
echo "   Largest index: $BIGGEST"
echo ""

echo "→ Step 5: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    # OLD CODE: echo "=== Deploy complete: every check passed. Open System: the disk total now matches the drive's label (1 TB, not 931 GB). ===" (named a 1 TB drive whatever the box has)
    echo "=== Deploy complete: every check passed. Open System: the disk total is now in decimal units, as on the drive's label. ==="
else
    echo "=== Deploy complete with ✗ lines above: paste them back. ==="
fi
