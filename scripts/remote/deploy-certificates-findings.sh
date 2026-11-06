#!/usr/bin/env bash
# Deploy the new Certificates page (NET-154) and check its figures on the device.
#
# Rebuilds the daemon (the complete certificate pass, /api/certificates/overview) and the web
# container (the new page, and the proxy's 60 s allowance for that path). Then:
#   - checks the overview answers for the last 24 hours, without printing the daemon token;
#   - runs scripts/remote/verify-certificates.py inside the daemon container: an independent
#     recount of 24 h, 7 d and 30 d, plus the time, size and memory limits;
#   - records Zeek's X509::relog_known_certificates_after, for the record.
#
# A 30-day pass within the limits (45 s, 5 MB, 300 MB) is a release requirement.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-certificates-findings.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="main"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

echo "=== Deploy: Certificates page with findings (NET-154) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
# A failed checkout or pull would rebuild the old code, so stop here instead
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Rebuild the daemon and web containers..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate the two containers (nothing else is touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 4: Wait for both containers to become healthy..."
WEB_STATUS="unknown"
DAEMON_STATUS="unknown"
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
        break
    fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "containers healthy" "$rc" "web=$WEB_STATUS daemon=$DAEMON_STATUS"
echo ""

echo "→ Step 5: The overview endpoint answers for the last 24 hours..."
# The daemon image has no curl; the token is read inside the container and never printed
OVERVIEW=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
token = open('/run/nettap-auth/daemon-token').read().strip()
to = datetime.now(timezone.utc)
q = f'from={(to - timedelta(hours=24)).strftime(\"%Y-%m-%dT%H:%M:%SZ\")}&to={to.strftime(\"%Y-%m-%dT%H:%M:%SZ\")}'
req = urllib.request.Request('http://localhost:8880/api/certificates/overview?' + q, headers={'X-NetTap-Daemon-Token': token})
start = time.monotonic()
try:
    r = json.load(urllib.request.urlopen(req, timeout=70))
    s = r['summary']
    print('200', f\"{time.monotonic() - start:.1f}s\", s['certificates'], 'certificates,', s['sites'], 'sites,', s['sessions'], 'sessions,', s['findings']['total'], 'findings')
except urllib.error.HTTPError as e:
    print(e.code, json.loads(e.read() or b'{}').get('error', ''))
except Exception as e:
    print('000', type(e).__name__, e)
" 2>&1 | tail -n 1)
if [ "${OVERVIEW%% *}" = "200" ]; then rc=0; else rc=1; fi
check "GET /api/certificates/overview" "$rc" "${OVERVIEW#* }"
echo ""

echo "→ Step 6: Recount 24 h, 7 d and 30 d from the same snapshot (read-only; up to a few minutes)..."
# shellcheck disable=SC2024  # the script is read by this user and piped in; sudo needn't read it
sudo docker exec -i nettap-storage-daemon python3 - < "$REPO_DIR/scripts/remote/verify-certificates.py" 2>&1 | grep -v "Warning"
rc=${PIPESTATUS[0]}
check "certificate figures match the recount, within the limits" "$rc"
echo ""

echo "→ Step 7: Zeek's certificate relog interval (for the record)..."
RELOG=$(sudo docker exec nettap-zeek-live bash -c 'grep -rhs "relog_known_certificates_after" /usr/local/zeek/share/zeek/site/ /usr/local/zeek/share/zeek/base/files/x509/ 2>/dev/null | head -n 3')
if [ -n "$RELOG" ]; then
    printf '%s\n' "$RELOG" | sed 's/^/   /'
else
    echo "   not set in the site or base scripts, so Zeek's default applies"
fi
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete — open Certificates in the dashboard ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
exit "$FAILED"
