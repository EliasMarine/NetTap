# shellcheck shell=bash
# shellcheck disable=SC2034  # the variables are used by the scripts that source this
# Shared checks for the NET-191 slice 2 device scripts (sourced, not run).
# Everything runs through `sudo docker …` (the device's sudo rule allows docker only); Python and jq run
# inside containers. Nothing here prints the daemon token or an ET Pro code.

LIVE="nettap-suricata-live"
DAEMON="nettap-storage-daemon"
SOCK="/var/run/suricata/suricata-command.socket"
SURICATA_LOG="/var/log/suricata/live/suricata.log"
STATUS_FILE="/run/nettap-rules/update-status.json"
MARKER_FILE="/run/nettap-rules/update-in-progress"
FREE_SOURCES="abuse.ch/sslbl-blacklist,echap/stalkerware,et/open,ipfire/dbl"  # sorted
FIRST='(.message | if type == "array" then .[0] else . end)'
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

live_jq() {  # live_jq <socket command> <jq filter>: Suricata's answer, filtered inside suricata-live
    # shellcheck disable=SC2016  # expanded by the container's sh
    sudo docker exec "$LIVE" sh -c 'suricatasc "$0" -c "$1" 2>/dev/null | jq -r "$2" 2>/dev/null' "$SOCK" "$1" "$2"
}
engine_stats() { live_jq ruleset-stats "$FIRST | \"\(.rules_loaded) \(.rules_failed)\""; }  # "<loaded> <failed>"
engine_reload() { live_jq ruleset-reload-time "$FIRST | .last_reload"; }

status_field() {  # status_field <field>: from the update status record ("" when there is none)
    sudo docker exec "$LIVE" jq -r ".$1 // empty" "$STATUS_FILE" 2>/dev/null
}
marker_present() { sudo docker exec "$LIVE" test -e "$MARKER_FILE"; }
rules_sha() { sudo docker exec "$LIVE" sha256sum /var/lib/suricata/rules/suricata.rules 2>/dev/null | cut -c1-16; }

enabled_sources() {  # the enabled rule sources, names only, sorted, comma-separated; fails if it can't ask
    local out
    out=$(sudo docker exec -u suricata "$LIVE" suricata-update list-enabled-sources --quiet \
        --suricata /usr/bin/suricata-offline --data-dir /var/lib/suricata --config /etc/suricata/update.yaml \
        --suricata-conf /etc/suricata/suricata.yaml 2>/dev/null) || return 1
    printf '%s\n' "$out" | sed -n '/^Enabled sources:/,$ s/^ *- *//p' | sed -E 's/[|=].*//' | sort | paste -sd, -
}

engine_started_since() {  # engine_started_since "<YYYY-mm-dd HH:MM:SS UTC>" <tries of 10 s>: ISO time or ""
    local line ts
    for _ in $(seq 1 "$2"); do
        line=$(sudo docker exec "$LIVE" grep "Engine started" "$SURICATA_LOG" 2>/dev/null | tail -1)
        ts=${line#*] }
        ts=${ts:0:19}
        if [ -n "$line" ] && ! [[ "$ts" < "$1" ]]; then
            echo "${ts/ /T}Z"
            return 0
        fi
        sleep 10
    done
    return 1
}

api() {  # api <METHOD> <path> [<json body>]: "<HTTP status> <body>"; the token is read inside the daemon
    sudo docker exec "$DAEMON" python3 -c '
import sys, urllib.request, urllib.error
token = open("/run/nettap-auth/daemon-token").read().strip()
body = sys.argv[3].encode() if len(sys.argv) > 3 else None
req = urllib.request.Request("http://localhost:8880" + sys.argv[2], data=body, method=sys.argv[1],
                             headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=330) as r:
        print(r.status, r.read().decode())
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
except Exception as e:
    print(0, type(e).__name__)
' "$@" 2>&1
}

json_get() {  # json_get <json> <jq filter>: jq runs in suricata-live (the host may have no jq)
    sudo docker exec -i "$LIVE" jq -r "$2" <<<"$1" 2>/dev/null
}

wait_update_finished() {  # wait_update_finished <attempt before> <tries of 10 s>: a newer attempt is recorded, no marker
    local attempt
    for _ in $(seq 1 "$2"); do
        attempt=$(status_field attempt)
        if [ -n "$attempt" ] && [ "$attempt" != "$1" ] && ! marker_present; then return 0; fi
        sleep 10
    done
    return 1
}

restart_live_locked() {  # restart suricata-live holding the rules lock (rules-lock.sh must be sourced)
    rules_lock_take "$LIVE" || { echo "   ✗ Could not take the rules lock (exit $?)"; return 1; }
    sudo docker restart "$LIVE" >/dev/null
    local rc=$?
    rules_lock_release
    return "$rc"
}

preflight_clean() {  # preflight_clean [<extra detail>]: exit 3 unless slice 2 is live and Suricata runs cleanly
    if ! sudo docker exec "$LIVE" grep -q 'nettap-rules-update shim' /usr/local/bin/suricata-update-rules.sh 2>/dev/null; then
        echo "   ✗ Slice 2 is not on suricata-live (no update shim). Run deploy-detection-slice2.sh first."
        exit 3
    fi
    SHA_BEFORE=$(rules_sha)
    read -r LOADED_BEFORE NFAILED_BEFORE <<<"$(engine_stats)"
    if [ -z "$SHA_BEFORE" ] || [ "${LOADED_BEFORE:-0}" -eq 0 ] || [ "${NFAILED_BEFORE:-x}" != 0 ]; then
        echo "   ✗ Suricata is not running cleanly (rules ${SHA_BEFORE:-missing}, ${LOADED_BEFORE:-?} loaded, ${NFAILED_BEFORE:-?} failed)"
        exit 3
    fi
    echo "   ✓ rules file $SHA_BEFORE, $LOADED_BEFORE rules loaded, 0 failed${1:+; $1}"
}
