#!/usr/bin/env bash
# Deploy detection slice 3 (NET-191): Settings › Suricata rules shows what the engine runs, and the
# owner can add their own alert rules. Tracking: tracking-fixes/2026-11-06-detection-accuracy.md
#
#   Own rules live in owner.rules on the suricata-custom-rules volume (rw in the daemon, ro in
#   suricata-live at Malcolm's custom rules dir). A save is checked, tested by Suricata (-T) in a
#   throwaway container on a snapshot in nettap-rules-staging, renamed into place and reloaded.
#
# Gates: before anything is built, slice 2 must be live and Malcolm's custom rules dir must be where
# the mount goes; after the daemon is recreated, owner.rules must exist and the check endpoint must
# answer. Either failing stops before suricata-live is touched.
# suricata-live is recreated holding the rules lock (scripts/remote/rules-lock.sh).
# Then, separately (it changes the device on purpose: saves a test rule, restarts, clears it):
#   bash /home/nettap/NetTap/scripts/remote/check-owner-rules.sh
# Rollback: set BRANCH to the previous commit's branch and redeploy; suricata-live recreated without
# the mount simply has no owner rules. Back up owner.rules before removing the volume.
# The full output is also saved to ~/nettap-detection-slice3.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-detection-slice3.sh
set -u
exec > >(tee "$HOME/nettap-detection-slice3.log") 2>&1

REPO_DIR="${NETTAP_REPO_DIR:-/home/nettap/NetTap}"  # override for tests only
BRANCH="feature/detection-slice3"  # set to main once the PR is merged
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
CUSTOM_DIR="/opt/suricata/rules/custom"
OWNER_FILE="$CUSTOM_DIR/owner.rules"
TEST_RULE='{"content": "alert dns any any -> any any (msg:\"NetTap deploy check\"; dns.query; content:\"nettap-selftest.invalid\"; nocase; sid:1999999; rev:1;)\n"}'
BAD_RULE='{"content": "drop dns any any -> any any (msg:\"x\"; sid:1999999;)\n"}'

echo "=== Deploy: detection slice 3 (Settings matches the device; own rules) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
PULLED=1
for attempt in 1 2 3 4 5; do
    if git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; then PULLED=0; break; fi
    echo "   pull failed (attempt $attempt/5), retrying in 5 s..."
    sleep 5
done
if [ "$PULLED" -ne 0 ]; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
# shellcheck source=scripts/remote/rules-checks.sh
. "$REPO_DIR/scripts/remote/rules-checks.sh"
# shellcheck source=scripts/remote/rules-lock.sh
. "$REPO_DIR/scripts/remote/rules-lock.sh"
trap rules_lock_release EXIT
echo ""

echo "→ Step 2: Gate — slice 2 is live and Malcolm reads custom rules where the volume goes..."
preflight_clean ""
DIR=$(sudo docker exec "$LIVE" printenv SURICATA_CUSTOM_RULES_DIR 2>/dev/null)
if [ "$DIR" != "/opt/suricata/rules" ]; then
    echo "   ✗ Malcolm's SURICATA_CUSTOM_RULES_DIR is '${DIR:-unset}', not /opt/suricata/rules — nothing was built or restarted"
    exit 1
fi
echo "   ✓ SURICATA_CUSTOM_RULES_DIR=$DIR (Malcolm lists its **/*.rules at start)"
echo ""

echo "→ Step 3: Build the daemon and the web container..."
for svc in nettap-storage-daemon nettap-web; do
    if ! "${COMPOSE[@]}" build "$svc"; then
        echo "   ✗ $svc build failed — nothing was restarted"
        exit 1
    fi
done
echo ""

echo "→ Step 4: Recreate the daemon and the web container..."
STARTED=$(date -u '+%Y-%m-%d %H:%M:%S')
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
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

echo "→ Step 5: Gate — the daemon side of own rules works (suricata-live not touched yet)..."
GATE=0
if sudo docker exec "$DAEMON" test -f /var/lib/nettap-suricata-custom/owner.rules &&
    sudo docker exec "$DAEMON" test -d /var/lib/nettap-rules-staging; then rc=0; else rc=1; GATE=1; fi
check "volumes" "$rc" "owner.rules made at daemon start; staging dir mounted"
CUSTOM=$(api GET /api/suricata/rules/custom)
if [ "${CUSTOM%% *}" = 200 ]; then rc=0; else rc=1; GATE=1; fi
check "GET own rules" "$rc" "HTTP ${CUSTOM%% *}, $(json_get "${CUSTOM#* }" '"\(.rule_count) rules, cap \(.max_rules) rules / \(.max_bytes) bytes"')"
GOOD=$(api POST /api/suricata/rules/custom/check "$TEST_RULE")
BAD=$(api POST /api/suricata/rules/custom/check "$BAD_RULE")
if [ "${GOOD%% *}" = 200 ] && [ "${BAD%% *}" = 400 ]; then rc=0; else rc=1; GATE=1; fi
check "check endpoint" "$rc" "alert rule HTTP ${GOOD%% *}; drop rule HTTP ${BAD%% *} ($(json_get "${BAD#* }" '.errors[0].message // .error'))"
if [ "$GATE" -ne 0 ]; then
    echo "   ✗ Gate failed — suricata-live was not recreated (it runs as before; own rules stay off)"
    exit 1
fi
echo ""

echo "→ Step 6: Recreate suricata-live holding the rules lock..."
rules_lock_take "$LIVE"
case $? in
    0) echo "   ✓ holding the rules lock" ;;
    *) echo "   - Couldn't take the rules lock (busy for 15 minutes, or the holder didn't start); recreating anyway (an interrupted update's marker makes the next start restore the last good rules)" ;;
esac
STARTED=$(date -u '+%Y-%m-%d %H:%M:%S')
"${COMPOSE[@]}" up -d --no-deps --force-recreate suricata-live
rules_lock_release
echo "   ✓ recreated at $STARTED UTC; lock released, so its startup update can take it"
echo ""

echo "→ Step 7: Wait for the startup rule update and the engine (≤ 15 min)..."
if ACTIVATED=$(engine_started_since "$STARTED" 90); then
    check "suricata-live" 0 "engine started at $ACTIVATED"
else
    check "suricata-live" 1 "no 'Engine started' in $SURICATA_LOG since $STARTED UTC"
fi
echo ""

echo "→ Step 8: What the new container runs..."
if sudo docker exec "$LIVE" grep -q "$OWNER_FILE" /etc/suricata/suricata.yaml; then rc=0; else rc=1; fi
check "rule files" "$rc" "suricata.yaml lists $OWNER_FILE"
MOUNT_RW=$(sudo docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$CUSTOM_DIR\"}}{{.RW}}{{end}}{{end}}" "$LIVE")
if [ "$MOUNT_RW" = false ]; then rc=0; else rc=1; fi
check "own rules mount" "$rc" "$CUSTOM_DIR read-only (RW=${MOUNT_RW:-not mounted})"
OTHER=$(sudo docker inspect -f '{{range .Mounts}}{{.Destination}} {{.Name}}{{println}}{{end}}' "$LIVE" | grep -E 'update-sources.yaml|rules-staging')
if [ -z "$OTHER" ]; then rc=0; else rc=1; fi
check "retired mounts" "$rc" "${OTHER:-no update-sources.yaml or staging mount}"
read -r LOADED NFAILED <<<"$(engine_stats)"
if [ "${LOADED:-0}" -gt 0 ] && [ "${NFAILED:-x}" = 0 ]; then rc=0; else rc=1; fi
check "engine" "$rc" "${LOADED:-?} rules loaded, ${NFAILED:-?} failed"
LIVE_STATUS=$(api GET /api/suricata/rules/live)
OWNER=$(json_get "${LIVE_STATUS#* }" '.owner_rules // "none"')
WANT=$(json_get "${CUSTOM#* }" '.rule_count')
UPDATE_STATE=$(json_get "${LIVE_STATUS#* }" '.update.state // "none"')
if [ "${LIVE_STATUS%% *}" = 200 ] && [ "$OWNER" = "$WANT" ] && [ "$UPDATE_STATE" = active ]; then rc=0; else rc=1; fi
check "Settings live status" "$rc" "HTTP ${LIVE_STATUS%% *}, own rules $OWNER (saved $WANT), update $UPDATE_STATE"
echo ""

echo "→ Step 9: Daemon errors since the restart, container status..."
ERRS=$(sudo docker logs --since "${STARTED/ /T}Z" "$DAEMON" 2>&1 | grep -E "Traceback|ERROR" | sed 's/^[0-9T:., -]*//' | sort | uniq -c | sort -rn | head -10)
if [ -z "$ERRS" ]; then
    check "daemon log" 0 "no errors or tracebacks since $STARTED UTC"
else
    check "daemon log" 1 "errors since $STARTED UTC:"
    echo "      ${ERRS//$'\n'/$'\n'      }"
fi
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web|suricata-live"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Detection slice 3 deployed and verified ==="
    echo "Next: bash $REPO_DIR/scripts/remote/check-owner-rules.sh"
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
