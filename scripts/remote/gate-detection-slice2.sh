#!/usr/bin/env bash
# Deploy gate for detection slice 2 (NET-191): try the new rule sources before suricata-live uses them.
# Plan: .codex-review/2026-11-06-detection-accuracy/PLAN.md, slice 2 step 2.
#
# Nothing live changes. A throwaway container of the live image (network on, 1 GiB, 1 CPU, live UID/GID)
# runs the new update path (config/suricata/nettap-rules-update.sh → Malcolm's updater → suricata-update
# with its own -T) on a fresh data dir, with the source list and disable.conf lines from the pulled
# docker-compose.yml. Then the staged rules must pass:
#   - only the IPFire categories Malware and Phishing active; every dataset an active rule loads is staged;
#     no SID in 1000000-1999999 (kept for the owner's own rules)
#   - the fixture replay on the staged rules: 0 failed rules, and the IPFire/Echap fixtures pass
#   - own traffic replayed with the live rules and the staged rules; the SID difference is printed
# deploy-detection-slice2.sh runs this first and stops if it fails. It can also be run on its own.
# Run as the normal user (NOT with sudo), from the repo you pulled:
#   bash /home/nettap/NetTap/scripts/remote/gate-detection-slice2.sh
# Exit: 0 passed, 1 a check failed, 3 could not start.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="$REPO_DIR/scripts/remote"
REPLAY_ROOT="${NETTAP_REPLAY_ROOT:-/home/nettap/nettap-replay}"
STAGE="$REPLAY_ROOT/stage-$(date -u +%Y%m%dT%H%M%SZ)"
OWN="$REPLAY_ROOT/own"
STARTUP_TIMEOUT_S=300  # Malcolm's SURICATA_UPDATE_STARTUP_TIMEOUT default; the startup update runs under it
# shellcheck source=scripts/remote/rules-checks.sh
. "$SCRIPTS/rules-checks.sh"

echo "=== Gate: detection slice 2 rule sources (nothing live changes) ==="
echo ""

echo "→ Step 1: Preflight..."
if ! IMAGE=$(sudo docker inspect -f '{{.Config.Image}}' "$LIVE" 2>/dev/null); then
    echo "   ✗ $LIVE not found"
    exit 3
fi
LIVE_ENV=$(sudo docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$LIVE")
PUID=$(printf '%s\n' "$LIVE_ENV" | sed -n 's/^PUID=//p')
PGID=$(printf '%s\n' "$LIVE_ENV" | sed -n 's/^PGID=//p')
PUID=${PUID:-1000}
PGID=${PGID:-1000}
if [ "$(id -u)" != "$PUID" ]; then
    echo "   ✗ Run this as the user with UID $PUID (the live Suricata's), not $(id -un)"
    exit 3
fi
# The new values, from the compose file just pulled (jq runs in the live image; the host may have none)
NEW_ENV=$(cd "$REPO_DIR" && sudo docker compose -f docker/docker-compose.yml config --format json suricata-live 2>/dev/null |
    sudo docker run --rm -i --network none --entrypoint jq "$IMAGE" -r \
        '.services["suricata-live"].environment | .SURICATA_UPDATE_ENABLE_SOURCES // "", .SURICATA_DISABLE_SIDS // ""')
SOURCES=$(sed -n 1p <<<"$NEW_ENV")
DISABLE_SIDS=$(sed -n 2p <<<"$NEW_ENV")
if [ -z "$SOURCES" ] || [ -z "$DISABLE_SIDS" ]; then
    echo "   ✗ Could not read SURICATA_UPDATE_ENABLE_SOURCES / SURICATA_DISABLE_SIDS from docker-compose.yml"
    exit 3
fi
echo "   ✓ image $IMAGE; UID:GID $PUID:$PGID"
echo "   sources: $SOURCES"
echo "   disable: $DISABLE_SIDS"
mkdir -p "$STAGE/etc" "$STAGE/opt" "$STAGE/data" "$STAGE/state" "$STAGE/log" "$STAGE/etc-nettap" || exit 3
echo ""

echo "→ Step 2: Copy the live Suricata config into $STAGE..."
for pair in /etc/suricata:etc /opt/suricata/include-configs:opt; do  # <live path>:<folder in $STAGE>
    path=${pair%:*}
    if ! sudo docker cp "$LIVE:$path" - 2>/dev/null | tar -xf - -C "$STAGE/${pair#*:}" 2>/dev/null; then
        echo "   ✗ Could not copy $path out of $LIVE"
        exit 3
    fi
    echo "   ✓ $path"
done
[ -f /etc/nettap/suricata-threshold.config ] && cp /etc/nettap/suricata-threshold.config "$STAGE/etc-nettap/"
# disable.conf as the new container's entrypoint will write it: each comma item, trimmed, appended once
DISABLE="$STAGE/etc/suricata/disable.conf"
touch "$DISABLE"
IFS=',' read -r -a ITEMS <<<"$DISABLE_SIDS"
for item in "${ITEMS[@]}"; do
    item=$(awk '{$1=$1};1' <<<"$item")
    [ -n "$item" ] && ! grep -qxF -- "$item" "$DISABLE" && printf '%s\n' "$item" >> "$DISABLE"
done
echo "   ✓ disable.conf: $(grep -vc '^ *#' "$DISABLE") line(s), incl. the IPFire allowlist"
echo ""

echo "→ Step 3: Fetch and test the new sources in a throwaway container (≤ 15 min)..."
START=$(date +%s)
# /usr/bin/suricata carries file capabilities; exec fails unless they are in the bounding set (see verify-detection.sh)
# shellcheck disable=SC2024  # the log is written as us, on purpose
sudo docker run --rm --name "nettap-stage-$$" --memory 1g --memory-swap 1g --cpus 1 --user "$PUID:$PGID" \
    --cap-drop ALL --cap-add NET_ADMIN --cap-add NET_RAW --cap-add IPC_LOCK --security-opt no-new-privileges \
    -e SURICATA_UPDATE_RULES=true -e "SURICATA_UPDATE_ENABLE_SOURCES=$SOURCES" \
    -e NETTAP_MALCOLM_UPDATE=/usr/local/bin/suricata-update-rules.sh -e NETTAP_RULES_SOURCES_FILE=/nonexistent \
    -v "$STAGE/etc/suricata:/etc/suricata:ro" -v "$STAGE/opt/include-configs:/opt/suricata/include-configs:ro" \
    -v "$STAGE/etc-nettap:/etc/nettap:ro" -v "$STAGE/data:/var/lib/suricata" -v "$STAGE/state:/run/nettap-rules" \
    -v "$STAGE/log:/var/log/suricata" \
    -v "$REPO_DIR/config/suricata/nettap-rules-update.sh:/opt/nettap-rules-update.sh:ro" \
    --entrypoint timeout "$IMAGE" -k 10 900 /bin/bash /opt/nettap-rules-update.sh update > "$STAGE/update.log" 2>&1
RC=$?
TOOK=$(($(date +%s) - START))
tail -5 "$STAGE/update.log" | sed 's/^/   | /'
STATE=$(grep -o '"state": *"[a-z]*"' "$STAGE/state/update-status.json" 2>/dev/null | grep -o '[a-z]*"$' | tr -d '"')
if [ "$RC" -eq 0 ] && [ "$STATE" = prepared ] && [ -s "$STAGE/data/rules/suricata.rules" ]; then rc=0; else rc=1; fi
check "staged update" "$rc" "exit $RC, status ${STATE:-none}, ${TOOK}s (full log: $STAGE/update.log)"
[ "$rc" -eq 0 ] || { echo ""; echo "=== Gate failed: the staged update did not finish — nothing live changed ==="; exit 1; }
if [ "$TOOK" -gt $((STARTUP_TIMEOUT_S * 4 / 5)) ]; then
    echo "   ! ${TOOK}s is close to the ${STARTUP_TIMEOUT_S}s limit on the startup update (1 CPU here; the live container"
    echo "     has more). If it hits the limit, the restart keeps the previous rules and the nightly update retries."
fi
STAGED="$STAGE/data/rules"
echo ""

echo "→ Step 4: Check the staged rules (allowlist, datasets, SID range)..."
sudo docker run --rm --network none --memory 512m --cpus 1 --user "$PUID:$PGID" --cap-drop ALL \
    --security-opt no-new-privileges -v "$SCRIPTS/verify_detection.py:/opt/verify_detection.py:ro" \
    -v "$STAGED:/rules:ro" --entrypoint python3 "$IMAGE" /opt/verify_detection.py check-staged /rules | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 5: Replay the fixtures on the staged rules..."
REPORT=$(bash "$SCRIPTS/verify-detection.sh" fixtures --rules "$STAGED" 2>&1)
RC=$?
# shellcheck disable=SC2001
sed 's/^/   /' <<<"$REPORT"
LOADED=$(grep -m1 '^Rules: ' <<<"$REPORT")
if [ "$RC" -eq 0 ] && [[ "$LOADED" =~ ^Rules:\ [1-9][0-9]*\ loaded,\ 0\ failed ]]; then rc=0; else rc=1; fi
check "fixture replay" "$rc" "exit $RC; ${LOADED:-no rule count}"
for name in ipfire-malware ipfire-phishing ipfire-disabled-doh echap-stalkerware; do
    if grep -q "PASS     $name\$" <<<"$REPORT"; then rc=0; else rc=1; fi
    check "$name" "$rc" "$(grep -m1 -E "(PASS|FAIL|SKIPPED) +$name" <<<"$REPORT" | sed 's/^ *//')"
done
echo ""

echo "→ Step 6: Own traffic, live rules vs staged rules..."
mkdir -p "$OWN"
if [ -z "$(find "$OWN" -maxdepth 1 -type f -print -quit)" ]; then
    # The newest closed capture file of a replayable size (not written to for 15 min; netsniff-ng rotates every 10)
    # shellcheck disable=SC2016  # expanded by the container's sh
    PICK=$(sudo docker run --rm --network none --user "$PUID:$PGID" -v docker_pcap-data:/pcap:ro --entrypoint sh "$IMAGE" -c \
        'find /pcap -type f -mmin +15 -size +5M -size -200M -printf "%T@ %p\n" 2>/dev/null | sort -rn | head -1 | cut -d" " -f2-')
    if [ -n "$PICK" ] && sudo docker run --rm --network none --user "$PUID:$PGID" -v docker_pcap-data:/pcap:ro \
        -v "$OWN:/own" --entrypoint cp "$IMAGE" "$PICK" /own/; then
        echo "   ✓ seeded $OWN with ${PICK##*/}"
    else
        echo "   - no closed capture file under 200 MB in docker_pcap-data; put PCAPs in $OWN to compare"
    fi
fi
if [ -n "$(find "$OWN" -maxdepth 1 -type f -print -quit)" ]; then
    RUNS=()
    for rules in "" "$STAGED"; do
        OUT=$(bash "$SCRIPTS/verify-detection.sh" own "$OWN" ${rules:+--rules "$rules"} 2>&1)
        RC=$?
        LABEL=${rules:+staged}
        grep -E '^(Runner exit code|Rules|Peak memory|Alerts|Distinct SIDs)' <<<"$OUT" | sed "s/^/   [${LABEL:-live}] /"
        RUN=$(sed -n 's/^Run kept in \([^ ]*\) .*/\1/p' <<<"$OUT")
        check "own traffic, ${LABEL:-live} rules" "$RC" "exit $RC (${RUN:-no run dir})"
        RUNS+=("$RUN/out")
    done
    if [ "${#RUNS[@]}" -eq 2 ] && [ -d "${RUNS[0]}" ] && [ -d "${RUNS[1]}" ]; then
        sudo docker run --rm --network none --memory 512m --user "$PUID:$PGID" --cap-drop ALL \
            --security-opt no-new-privileges -v "$SCRIPTS/verify_detection.py:/opt/verify_detection.py:ro" \
            -v "${RUNS[0]}:/a:ro" -v "${RUNS[1]}:/b:ro" --entrypoint python3 "$IMAGE" \
            /opt/verify_detection.py diff-sids /a /b | sed 's/^/   /'
    fi
fi
echo ""

echo "Staged run kept in $STAGE"
if [ "$FAILED" -eq 0 ]; then
    echo "=== Gate passed ==="
    exit 0
fi
echo "=== Gate failed (✗ lines above) — nothing live changed ==="
exit 1
