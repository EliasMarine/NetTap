#!/usr/bin/env bash
# Deploy NET-344 (every downloadable backup restores) and check it on the box (plan §5, G11):
#   - nginx's new config is tested in a one-off container before anything is rebuilt;
#   - the daemon and web images are rebuilt; daemon, web and nginx are recreated (nginx is
#     recreated, not reloaded: a checkout can replace the bind-mounted file's inode);
#   - the running containers are the images just built, and nginx -T shows the backup location
#     with client_max_body_size 16m and proxy_read_timeout 300s;
#   - through authenticated nginx at https://localhost: the export is classified by
#     classify_backup_export.py (a size 413 or a legacy_excluded_ips 422 is a finding for the
#     owner, anything else but a 200 fails); a 200's exact bytes must validate; an empty-sections
#     document of limit - 1 bytes is accepted by validate and by import (applied: []), and the
#     same document at the limit gets 413 from both;
#   - isolated: verify_backup_size.py runs in a throwaway copy of the daemon image (no network,
#     no mounts): 32 full-size pictures and enough acknowledgements to pass the limit, exported,
#     fitted and restored into temp paths;
#   - the daemon's memory, the logs since the recreate, and container status.
# Nothing writes live data: the export and validate only read, and the import has no sections.
# The session is signed inside nettap-web for 60 s per request and never printed.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-backup-size.sh
# To try a branch before it merges: BRANCH=fix/backup-size bash ...
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
DAEMON_IMAGE="nettap/storage-daemon:latest"
WEB_IMAGE="nettap/web:latest"
LIMIT=$((16 * 1024 * 1024))  # services.config_backup.RESTORE_LIMIT_BYTES: a body restores when it is under this
BACKUP_LOCATION='location ~ ^/api/backup/(import|validate)$ {'
EMPTY_DOC='{"metadata":{"schema_version":2},"sections":{}'  # its closing brace comes after the padding
FAILED=0
FINDINGS=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

check_eq() {  # check_eq LABEL ACTUAL EXPECTED
    if [ "$2" = "$3" ]; then check "$1" 0 "$2"; else check "$1" 1 "$2, expected $3"; fi
}

# A 60-second session, signed inside nettap-web with its own secret. It is never printed and
# never on a command line: printf is a shell builtin and curl reads the header from stdin.
MINT='const fs=require("fs"),jwt=require("jsonwebtoken");const d=process.env.DATA_DIR||"/var/lib/nettap-web";const s=process.env.JWT_SECRET||fs.readFileSync(d+"/jwt-secret.txt","utf8").trim();const u=JSON.parse(fs.readFileSync(d+"/users.json","utf8")).users[0].username;process.stdout.write(jwt.sign({username:u,role:"admin"},s,{expiresIn:60}))'

signed_in() {  # signed_in CURL_ARGS...: one curl through nginx with a fresh session; prints nosession if none
    local session
    session=$(sudo docker exec -w /app nettap-web node -e "$MINT" 2>/dev/null)
    if [ -z "$session" ]; then echo "nosession"; return; fi
    printf 'Cookie: nettap_token=%s\n' "$session" | curl -sk -H @- "$@"
}

post() {  # post ROUTE FILE OUT: the file's exact bytes to /api/backup/ROUTE; prints the status
    signed_in -o "$3" -w '%{http_code}' --max-time 300 -H 'Content-Type: application/json' \
        --data-binary "@$2" "https://localhost/api/backup/$1"
}

reply() {  # reply FILE EXPR: EXPR over the JSON reply d, worked out in the daemon (no python on the host)
    # shellcheck disable=SC2024  # the user reads the file; only docker needs sudo
    sudo docker exec -i nettap-storage-daemon python3 -c "import json, sys; d = json.load(sys.stdin); print($2)" < "$1" 2>/dev/null || echo "unreadable"
}

padded() {  # padded SIZE FILE: a valid backup with no sections, exactly SIZE bytes
    { printf '%s' "$EMPTY_DOC"; head -c $(( $1 - ${#EMPTY_DOC} - 1 )) /dev/zero | tr '\0' ' '; printf '}'; } > "$2"
}

daemon_rss_mb() {  # the daemon process's resident memory, in MB (not docker stats: F1 lesson)
    sudo docker top nettap-storage-daemon -o pid,rss,args 2>/dev/null | awk '$3 ~ /python/ && / main\.py/ { if ($2 > m) m = $2 } END { printf "%d", m / 1024 }'
}

echo "=== Deploy: every downloadable backup restores (NET-344, $BRANCH) ==="
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

echo "→ Step 2: Test the new nginx config in a one-off container..."
if ! NGINX_TEST=$("${COMPOSE[@]}" run --rm --no-deps --entrypoint nginx nettap-nginx -t 2>&1); then
    echo "$NGINX_TEST" | tail -5 | sed 's/^/   /'
    echo "   ✗ nginx -t failed — nothing was rebuilt or restarted"
    exit 1
fi
echo "   ✓ nginx -t: $(echo "$NGINX_TEST" | grep -o 'test is successful' || echo ok)"
echo ""

echo "→ Step 3: Build the daemon and web images..."
# a failed build must stop here: recreating would bring back the OLD images unnoticed
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
BUILT_DAEMON=$(sudo docker image inspect "$DAEMON_IMAGE" --format '{{.Id}}' 2>/dev/null)
BUILT_WEB=$(sudo docker image inspect "$WEB_IMAGE" --format '{{.Id}}' 2>/dev/null)
echo "   ✓ Images built (daemon ${BUILT_DAEMON:7:12}, web ${BUILT_WEB:7:12})"
echo ""

echo "→ Step 4: Recreate the daemon, web and nginx containers (nothing else is touched)..."
NGINX_BEFORE=$(sudo docker inspect --format '{{.Id}}' nettap-nginx 2>/dev/null)
RECREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web nettap-nginx; then
    echo "   ✗ Recreation failed — the checks below would test the old containers"
    exit 1
fi
RUNNING_DAEMON=$(sudo docker inspect --format '{{.Image}}' nettap-storage-daemon 2>/dev/null)
RUNNING_WEB=$(sudo docker inspect --format '{{.Image}}' nettap-web 2>/dev/null)
NGINX_AFTER=$(sudo docker inspect --format '{{.Id}}' nettap-nginx 2>/dev/null)
if [ -n "$BUILT_DAEMON" ] && [ "$RUNNING_DAEMON" = "$BUILT_DAEMON" ]; then rc=0; else rc=1; fi
check "daemon image ID" "$rc" "running ${RUNNING_DAEMON:7:12}, built ${BUILT_DAEMON:7:12}"
if [ -n "$BUILT_WEB" ] && [ "$RUNNING_WEB" = "$BUILT_WEB" ]; then rc=0; else rc=1; fi
check "web image ID" "$rc" "running ${RUNNING_WEB:7:12}, built ${BUILT_WEB:7:12}"
if [ -n "$NGINX_AFTER" ] && [ "$NGINX_AFTER" != "$NGINX_BEFORE" ]; then rc=0; else rc=1; fi
check "nginx container recreated" "$rc" "${NGINX_BEFORE:0:12} -> ${NGINX_AFTER:0:12}"
echo ""

echo "→ Step 5: Wait for the three containers to become healthy..."
WEB="unknown"; DAEMON="unknown"; NGINX="unknown"
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    NGINX=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-nginx 2>/dev/null || echo "unknown")
    [ "$WEB" = "healthy" ] && [ "$DAEMON" = "healthy" ] && [ "$NGINX" = "healthy" ] && break
    echo "   waiting... web=$WEB daemon=$DAEMON nginx=$NGINX ($i/30)"
    sleep 5
done
check_eq "nettap-web health" "$WEB" "healthy"
check_eq "nettap-storage-daemon health" "$DAEMON" "healthy"
check_eq "nettap-nginx health" "$NGINX" "healthy"
if [ "$WEB$DAEMON$NGINX" != "healthyhealthyhealthy" ]; then
    echo "     Logs: sudo docker logs nettap-storage-daemon --tail 50"
    echo "=== Deploy stopped: a container isn't healthy ==="
    exit 1
fi
echo ""

echo "→ Step 6: The restore limits are live..."
BLOCK=$(sudo docker exec nettap-nginx nginx -T 2>/dev/null | grep -F -A 20 "$BACKUP_LOCATION" | sed '/}/q')
LIMITS=$(echo "$BLOCK" | grep -oE '^[[:space:]]*(client_max_body_size|proxy_read_timeout) [^;]+' | xargs)
check_eq "nginx backup location" "$LIMITS" "client_max_body_size 16m proxy_read_timeout 300s"
check_eq "web BODY_SIZE_LIMIT" "$(sudo docker exec nettap-web printenv BODY_SIZE_LIMIT 2>/dev/null || echo unset)" "16M"
DAEMON_LIMITS=$(sudo docker exec nettap-storage-daemon python3 -c "from api.server import MAX_REQUEST_BYTES as m; from services.config_backup import RESTORE_LIMIT_BYTES as r; print(m, r)" 2>/dev/null || echo "unknown")
check_eq "daemon client_max_size and RESTORE_LIMIT_BYTES" "$DAEMON_LIMITS" "$LIMIT $LIMIT"
echo ""

echo "→ Step 7: Through authenticated nginx (nothing is written)..."
TMPD=$(mktemp -d)
trap 'rm -rf "$TMPD"' EXIT
RSS_BEFORE=$(daemon_rss_mb)
: > "$TMPD/export.json"
STATUS=$(signed_in -o "$TMPD/export.json" -D "$TMPD/export.headers" -w '%{http_code}' --max-time 120 https://localhost/api/backup/export)
# The classifier runs in the daemon container as -c; stdin carries the export's bytes
# shellcheck disable=SC2024  # the user reads the files; only docker needs sudo
VERDICT=$(sudo docker exec -i nettap-storage-daemon python3 -c "$(cat scripts/remote/classify_backup_export.py)" "$STATUS" < "$TMPD/export.json" 2>&1)
case "$VERDICT" in
    OK\ *)
        check "export" 0 "$VERDICT"
        if grep -qi '^cache-control: *no-store' "$TMPD/export.headers" && grep -qi '^content-disposition: *attachment' "$TMPD/export.headers"; then rc=0; else rc=1; fi
        check "export headers: Cache-Control no-store, Content-Disposition attachment" "$rc"
        STATUS=$(post validate "$TMPD/export.json" "$TMPD/validate.json")
        check_eq "the export's exact bytes validate" "$STATUS $(reply "$TMPD/validate.json" 'd.get("is_valid")')" "200 True"
        ;;
    FINDING\ *)
        FINDINGS=1
        echo "   ! export: $VERDICT"
        echo "     The owner has to act on this (the message says how); the checks below still run."
        ;;
    *)
        check "export" 1 "${VERDICT:-no verdict}"
        ;;
esac

padded $((LIMIT - 1)) "$TMPD/under.json"
padded "$LIMIT" "$TMPD/at.json"
check_eq "padded documents' sizes" "$(wc -c < "$TMPD/under.json" | xargs) $(wc -c < "$TMPD/at.json" | xargs)" "$((LIMIT - 1)) $LIMIT"
STATUS=$(post validate "$TMPD/under.json" "$TMPD/r1.json")
check_eq "limit - 1 bytes: validate accepts" "$STATUS $(reply "$TMPD/r1.json" 'd.get("is_valid")')" "200 True"
STATUS=$(post import "$TMPD/under.json" "$TMPD/r2.json")
check_eq "limit - 1 bytes: import accepts, applies nothing" "$STATUS $(reply "$TMPD/r2.json" 'd.get("success") is True and d.get("applied") == []')" "200 True"
for route in validate import; do
    STATUS=$(post "$route" "$TMPD/at.json" "$TMPD/r3.json")
    check_eq "limit bytes: $route refuses with 413" "$STATUS" "413"
    echo "     $(reply "$TMPD/r3.json" 'd.get("error")')"
done
RSS_AFTER=$(daemon_rss_mb)
echo ""

echo "→ Step 8: Isolated round trip in a throwaway copy of the daemon image (no network, no mounts)..."
if [ -z "$RUNNING_DAEMON" ] || [ "$RUNNING_DAEMON" != "$BUILT_DAEMON" ]; then
    check "isolated round trip" 1 "skipped: the running image isn't the one built"
else
    # shellcheck disable=SC2024  # the user reads the script; docker gets it on stdin
    OUT=$(sudo docker run --rm -i --network none --entrypoint python3 "$BUILT_DAEMON" - < scripts/remote/verify_backup_size.py 2>&1)
    echo "$OUT" | grep -E "^   " || true
    if echo "$OUT" | grep -qx "BACKUP-SIZE-OK"; then rc=0; else rc=1; fi
    check "32 pictures + trimmed acknowledgements: exported, validated, restored" "$rc" "$(echo "$OUT" | tail -n 1)"
fi
echo ""

echo "→ Step 9: Memory, logs since the recreate, status..."
echo "   · daemon VmRSS ${RSS_BEFORE} MB before the probes, ${RSS_AFTER} MB after, $(daemon_rss_mb) MB now"
for name in nettap-storage-daemon nettap-web; do
    echo "   · $name errors since $RECREATED:"
    sudo docker logs "$name" --since "$RECREATED" 2>&1 | grep -iE "error|exception|traceback" | tail -n 5 | sed 's/^/     /' || true
done
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon|nettap-nginx"
echo ""

if [ "$FAILED" -ne 0 ]; then
    echo "=== Deploy finished with failures (✗ above) ==="
    exit 1
elif [ "$FINDINGS" -ne 0 ]; then
    echo "=== Deploy complete; every check passed, with a finding for the owner (! above) ==="
else
    echo "=== Deploy complete: every check passed ==="
fi
echo "Open Settings › Backup, download a backup, then choose it under Restore (don't apply it)."
