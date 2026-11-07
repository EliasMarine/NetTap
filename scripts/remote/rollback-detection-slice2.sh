#!/usr/bin/env bash
# Roll back detection slice 2 (NET-191), in the plan's order: remove the ET Pro code first, then go back to
# the code before slice 2 and recreate suricata-live (ET Open only again). ~/nettap-rules-baseline is kept.
# The nettap-rules-state volume is left in place (unused by the old compose file; delete it by hand later).
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/rollback-detection-slice2.sh [<branch or tag before slice 2>]
set -u

REPO_DIR="/home/nettap/NetTap"
TARGET="${1:-main}"  # main before the slice 2 PR merged; after it merged, pass the tag/commit before it
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
cd "$REPO_DIR" || { echo "✗ $REPO_DIR not found"; exit 1; }
# shellcheck source=scripts/remote/rules-checks.sh
. "$REPO_DIR/scripts/remote/rules-checks.sh"
# shellcheck source=scripts/remote/rules-lock.sh
. "$REPO_DIR/scripts/remote/rules-lock.sh"
trap rules_lock_release EXIT

echo "=== Roll back detection slice 2 to $TARGET ==="
echo ""

echo "→ Step 1: Remove the ET Pro code (if one is saved)..."
sudo docker exec "$DAEMON" rm -f /etc/nettap/suricata.env
# OLD CODE START — review round 2: passed when the daemon container was down (docker exec failed)
# if sudo docker exec "$DAEMON" test -e /etc/nettap/suricata.env; then rc=1; else rc=0; fi
# OLD CODE END
sudo docker exec "$DAEMON" test ! -e /etc/nettap/suricata.env
rc=$?
check "ET Pro code" "$rc" "/etc/nettap/suricata.env removed (the daemon container must be running to check)"
[ "$rc" -eq 0 ] || exit 1
echo ""

echo "→ Step 2: Check out $TARGET..."
if ! { git fetch origin && git checkout "$TARGET" && { git symbolic-ref -q HEAD >/dev/null && git pull origin "$TARGET" || true; }; }; then
    echo "   ✗ Could not check out $TARGET — nothing else was changed"
    exit 1
fi
if grep -q 'nettap-rules-update.sh start' docker/docker-compose.yml; then
    echo "   ✗ $TARGET still has slice 2 (nettap-rules-update.sh in docker-compose.yml); pass the commit before it"
    exit 1
fi
echo "   ✓ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 3: Build and recreate the daemon and the web container..."
for svc in nettap-storage-daemon nettap-web; do
    "${COMPOSE[@]}" build "$svc" || { echo "   ✗ $svc build failed"; exit 1; }
done
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 4: Recreate suricata-live holding the rules lock..."
rules_lock_take "$LIVE"
case $? in
    0 | 2) ;;
    # OLD CODE START — review round 2: gave up, so a stuck update could block a rollback for ever
    # *) echo "   ✗ A rule update held the lock for 15 minutes — not recreated; run this again"; exit 1 ;;
    # OLD CODE END
    # Safe: the stopped update leaves its marker, and the next start restores the last good rules first
    *) echo "   - A rule update held the lock for 15 minutes; recreating anyway (its marker makes the next start restore the last good rules)" ;;
esac
# /var/lib/suricata is an anonymous volume that survives the recreate: drop slice 2's enabled sources
# (an ET Pro source carries the code) and its source list, so the old compose file is back on ET Open.
# As Malcolm's user, who owns them, so root never follows a link left in that directory.
# shellcheck disable=SC2016
sudo docker exec -u suricata "$LIVE" sh -c 'rm -f /var/lib/suricata/update/sources/*.yaml /var/lib/suricata/update/nettap-enable-sources'
if sudo docker exec "$LIVE" sh -c '! ls /var/lib/suricata/update/sources/*.yaml >/dev/null 2>&1 && test ! -e /var/lib/suricata/update/nettap-enable-sources'; then rc=0; else rc=1; fi
check "slice 2 sources removed" "$rc" "/var/lib/suricata/update/sources/*.yaml and nettap-enable-sources"
STARTED=$(date -u '+%Y-%m-%d %H:%M:%S')
"${COMPOSE[@]}" up -d --no-deps --force-recreate suricata-live
rules_lock_release
echo ""

echo "→ Step 5: Verify (≤ 15 min for the startup update)..."
if ACTIVATED=$(engine_started_since "$STARTED" 90); then rc=0; else rc=1; fi
check "suricata-live" "$rc" "engine started ${ACTIVATED:-not seen since $STARTED UTC}"
# OLD CODE START — review round 2: passed when suricata-update couldn't be asked (empty answer)
# GOT=$(enabled_sources)
# if [ -z "$GOT" ] || [ "$GOT" = "et/open" ]; then rc=0; else rc=1; fi
# OLD CODE END
# The old compose file names no source, and suricata-update then uses ET Open with no source file, so
# "none named" is right here; the rules file below must also hold ET Open rules.
if GOT=$(enabled_sources) && { [ -z "$GOT" ] || [ "$GOT" = "et/open" ]; }; then rc=0; else rc=1; fi
check "enabled sources" "$rc" "${GOT:-none named, so ET Open} (want ET Open only)"
ETOPEN=$(sudo docker exec "$LIVE" grep -cE '^alert .*msg:"ET ' /var/lib/suricata/rules/suricata.rules)
if [ "${ETOPEN:-0}" -gt 0 ] 2>/dev/null; then rc=0; else rc=1; fi
check "ET Open rules" "$rc" "${ETOPEN:-?} active ET rules (want more than 0)"
EXTRA=$(sudo docker exec "$LIVE" grep -cE '^alert .*msg:"(IPFire DBL|PTS STALKERWARE|SSLBL)' /var/lib/suricata/rules/suricata.rules)
if [ "${EXTRA:-x}" = 0 ]; then rc=0; else rc=1; fi
check "rules" "$rc" "${EXTRA:-?} active IPFire/Echap/SSLBL rules (want 0; the startup update replaced them)"
read -r LOADED NFAILED <<<"$(engine_stats)"
if [ "${LOADED:-0}" -gt 0 ] && [ "${NFAILED:-x}" = 0 ]; then rc=0; else rc=1; fi
check "engine" "$rc" "${LOADED:-?} rules loaded, ${NFAILED:-?} failed"
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web|suricata-live"
echo ""
if [ "$FAILED" -eq 0 ]; then echo "=== Rolled back ==="; else echo "=== Finished with ✗ lines above — paste this output back ==="; fi
