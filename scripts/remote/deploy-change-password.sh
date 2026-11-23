#!/usr/bin/env bash
# Deploy NET-357 (signed-out pages go to sign-in) and NET-358 (change your password in Settings, with
# sessions tied to the password and a new session key) together, after both PRs merge to main.
#
# Web only: rebuilds and recreates nettap-web alone (--no-deps; the daemon, OpenSearch, nginx and
# capture are not touched). Everyone signs in again once: sessions from before the deploy don't name
# a password, so the new release refuses them.
#
# Step 0 changes nothing. It stops if the running nettap-web has JWT_SECRET (an older NetTap would
# still trust sessions signed with it, so a rollback could undo a password change), and counts the
# accounts in users.json (inside the container; names never leave it).
# Step 1, before any git or docker change, fingerprints jwt-secret.txt (the key every older build
# reads) inside the container, as the old reader sees it (whitespace stripped), and keeps it in a
# variable: no key or hash is printed. It then records the running web image as
# nettap/web:rollback-net358 and in $RECORD, so rollback-change-password.sh can put it back. A later
# run keeps the record from the first run and only checks it still matches the tag.
# After the deploy the new release must have replaced jwt-secret.txt (it does so at every start),
# and a session minted by mint-session.cjs must work.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-change-password.sh
# To try a branch before it merges:
#   BRANCH=feature/change-password bash /home/nettap/NetTap/scripts/remote/deploy-change-password.sh
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
RECORD="${RECORD:-/home/nettap/.nettap-rollback-net358}"
TAG="nettap/web:rollback-net358"
WEB_IMAGE="nettap/web:latest"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
BASE="https://localhost"
MINT="$REPO_DIR/scripts/remote/mint-session.cjs"
EMPTY_FORM='"Enter your current password and a new one."'  # the endpoint's 400 for {}, as a JSON string
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

check_eq() {  # check_eq LABEL ACTUAL EXPECTED
    if [ "$2" = "$3" ]; then check "$1" 0 "$2"; else check "$1" 1 "$2, expected $3"; fi
}

unchanged() {  # stop before anything was changed
    echo "   ✗ $1 — nothing was changed"
    exit 1
}

record_id() { sed -n 's/^web=//p' "$RECORD" 2>/dev/null; }
tag_id() { sudo docker image inspect -f '{{.Id}}' "$TAG" 2>/dev/null; }

web_env_has() {  # web_env_has NAME: nettap-web's environment sets NAME (only names are matched; no value is printed)
    sudo docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' nettap-web 2>/dev/null | grep -q "^$1="
}

account_count() {  # how many accounts users.json holds (0 when it doesn't exist); empty when it can't be read
    # Worked out inside nettap-web, silently: a JSON parse error can quote the file
    sudo docker exec nettap-web node -e 'try{const t=require("fs").readFileSync((process.env.DATA_DIR||"/var/lib/nettap-web")+"/users.json","utf8");const u=JSON.parse(t).users;if(!Array.isArray(u))process.exit(1);console.log(u.length)}catch(e){if(e.code==="ENOENT")console.log(0);else process.exit(1)}' 2>/dev/null
}

key_state() {  # key_state FILE: "none", or ok:/bad: (128 lowercase hex or not) and the sha256 of the key, whitespace stripped
    # Read inside nettap-web by sh ($1, $f, $k are its own); the caller keeps the result and never prints it
    sudo docker exec nettap-web sh -c 'f="${DATA_DIR:-/var/lib/nettap-web}/$1"
        [ -e "$f" ] || { echo none; exit 0; }
        k=$(tr -d "[:space:]" < "$f") || exit 1
        case "$k" in *[!0-9a-f]*) s=bad ;; *) if [ ${#k} -eq 128 ]; then s=ok; else s=bad; fi ;; esac
        printf "%s:" "$s"
        printf "%s" "$k" | sha256sum | cut -d" " -f1' sh "$1" 2>/dev/null
}

signed_in() {  # signed_in CURL_ARGS...: one curl through nginx with a fresh 60 s session; prints nosession if none
    local session
    # Never printed and never on a command line: printf is a shell builtin and curl reads the header from stdin
    # shellcheck disable=SC2024  # the user reads the file; only docker needs sudo
    session=$(sudo docker exec -i -w /app nettap-web node - < "$MINT")
    if [ -z "$session" ]; then echo "nosession"; return; fi
    printf 'Cookie: nettap_token=%s\n' "$session" | curl -sk -H @- "$@"
}

status_of() {  # status_of CURL_ARGS...: the HTTP status of one signed-out request
    curl -sk -o /dev/null --max-time 20 -w '%{http_code}' "$@" || true
}

redirect_of() {  # redirect_of PATH: "STATUS LOCATION" of a signed-out GET
    curl -sk -o /dev/null --max-time 20 -w '%{http_code} %{redirect_url}' "$BASE$1" || true
}

echo "=== Deploy: change password + signed-out pages (NET-357 + NET-358, $BRANCH) ==="
echo ""

echo "→ Step 0: Check the running web container (nothing is changed here)..."
if [ "$(sudo docker inspect -f '{{.State.Running}}' nettap-web 2>/dev/null)" != "true" ]; then
    echo "   ✗ nettap-web isn't running — nothing was changed. Start it, then run this script again:"
    echo "     sudo docker compose -f $REPO_DIR/docker/docker-compose.yml up -d nettap-web"
    exit 1
fi
if web_env_has JWT_SECRET; then
    echo "   ✗ nettap-web has JWT_SECRET set — nothing was changed"
    echo "   An older NetTap would still trust sessions signed with it, so a rollback could undo a password change."
    # OLD CODE: echo "   Remove JWT_SECRET from the web container's settings (or move a fixed key to NETTAP_SESSION_SECRET)," (NET-358 review: NETTAP_SESSION_SECRET is gone)
    echo "   Remove JWT_SECRET from the web container's settings,"
    echo "   recreate the container, then run this script again:"
    echo "     sudo docker compose -f $REPO_DIR/docker/docker-compose.yml up -d --no-deps --force-recreate nettap-web"
    echo "     bash $REPO_DIR/scripts/remote/deploy-change-password.sh"
    exit 1
fi
echo "   ✓ No JWT_SECRET in nettap-web's environment"
ACCOUNTS=$(account_count)
case "$ACCOUNTS" in
    '' | *[!0-9]*) unchanged "Couldn't read users.json inside nettap-web" ;;
esac
if [ "$ACCOUNTS" -gt 0 ]; then
    echo "   ✓ users.json holds $ACCOUNTS account(s): the signed-in checks run"
else
    echo "   ✓ No account yet (setup not done): the first-run checks run instead, and the store stays empty"
fi
echo ""

echo "→ Step 1: Fingerprint the old key and record the web image to roll back to..."
LEGACY_BEFORE=$(key_state jwt-secret.txt)
case "$LEGACY_BEFORE" in
    none) echo "   ✓ No jwt-secret.txt yet (no session was ever issued): recorded as none" ;;
    ok:* | bad:*) echo "   ✓ Fingerprinted jwt-secret.txt as the old reader sees it (not printed)" ;;
    *) unchanged "Couldn't read jwt-secret.txt inside nettap-web" ;;
esac
if [ -s "$RECORD" ]; then
    # A later run: the running image may already be the feature, so only the record and tag must agree.
    REC=$(record_id)
    TAGGED=$(tag_id)
    if [ -z "$REC" ] || [ "$REC" != "$TAGGED" ]; then
        unchanged "$RECORD says ${REC:-(no web= line)} but $TAG is ${TAGGED:-missing}"
    fi
    echo "   ✓ Keeping the record from the first run: $TAG is ${REC:7:12}"
else
    RUNNING=$(sudo docker inspect -f '{{.Image}}' nettap-web 2>/dev/null)
    [ -n "$RUNNING" ] || unchanged "Couldn't read the running web image"
    sudo docker tag "$RUNNING" "$TAG" || unchanged "Couldn't tag the running web image as $TAG"
    printf 'web=%s\n' "$RUNNING" > "$RECORD" || unchanged "Couldn't write $RECORD"
    REC=$(record_id)
    TAGGED=$(tag_id)
    if [ -z "$REC" ] || [ "$REC" != "$RUNNING" ] || [ "$TAGGED" != "$RUNNING" ]; then
        unchanged "Record (${REC:-empty}), running image ($RUNNING) and $TAG (${TAGGED:-missing}) differ"
    fi
    echo "   ✓ Tagged the running image ${RUNNING:7:12} as $TAG and wrote $RECORD"
fi
echo ""

echo "→ Step 2: Update the code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
[ -f "$MINT" ] || { echo "   ✗ $MINT is missing on $BRANCH — nothing was rebuilt"; exit 1; }
echo ""

echo "→ Step 3: Build the web container..."
# A failed build must stop here: recreating would bring back the OLD image unnoticed.
if ! "${COMPOSE[@]}" build nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
BUILT=$(sudo docker image inspect -f '{{.Id}}' "$WEB_IMAGE" 2>/dev/null)
echo "   ✓ Image built (${BUILT:7:12})"
echo ""

echo "→ Step 4: Recreate the web container (nothing else is touched)..."
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web; then
    echo "   ✗ docker compose up failed. To go back: bash $REPO_DIR/scripts/remote/rollback-change-password.sh"
    exit 1
fi
echo "   ✓ Recreated"
echo ""

echo "→ Step 5: Wait for it to become healthy..."
WEB="unknown"
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    [ "$WEB" = "healthy" ] && break
    echo "   waiting... web=$WEB ($i/30)"
    sleep 5
done
if [ "$WEB" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-web health" "$rc" "$WEB"
RUNNING_NOW=$(sudo docker inspect --format='{{.Image}}' nettap-web 2>/dev/null)
if [ -n "$BUILT" ] && [ "$RUNNING_NOW" = "$BUILT" ]; then rc=0; else rc=1; fi
check "nettap-web runs the image just built" "$rc" "running ${RUNNING_NOW:7:12}, built ${BUILT:7:12}"
echo ""

echo "→ Step 6: Checks that need no session..."
check_eq "/api/health answers" "$(status_of "$BASE/api/health")" 200
JSON_POST=(-X POST -H 'Content-Type: application/json' --data '{}' "$BASE/api/account/password")
check_eq "signed-out POST /api/account/password is refused" "$(status_of "${JSON_POST[@]}")" 401
check_eq "the same POST from another site is refused" "$(status_of -H 'Sec-Fetch-Site: cross-site' "${JSON_POST[@]}")" 403
LEGACY_AFTER=$(key_state jwt-secret.txt)
LEGACY_REPLACED=0
if [ "${LEGACY_AFTER%%:*}" = "ok" ] && { [ "$LEGACY_BEFORE" = "none" ] || [ "${LEGACY_AFTER#*:}" != "${LEGACY_BEFORE#*:}" ]; }; then
    LEGACY_REPLACED=1
    check "jwt-secret.txt (the key older builds read) was replaced" 0
else
    check "jwt-secret.txt (the key older builds read) was replaced" 1 "${LEGACY_AFTER%%:*}: unchanged, missing or not a valid key"
    if [ "$WEB" != "healthy" ]; then
        # NET-358 review: it didn't start, so the key couldn't be read; a restart would only fail the same way
        echo "   The new web app didn't start. Read why:"
        echo "     sudo docker logs nettap-web --tail 50"
        echo "   If the log names a malformed jwt-secret-v2.txt, the old key was already replaced (that happens first),"
        echo "   so rolling back is safe:"
        echo "     bash $REPO_DIR/scripts/remote/rollback-change-password.sh"
        echo "   Any other start failure (for example a full disk) may have stopped before replacing it."
        echo "   Fix that and run this script again rather than roll back:"
        echo "     bash $REPO_DIR/scripts/remote/deploy-change-password.sh"
    else
        echo "   Do NOT roll back now: an older image would still trust the old key."
        echo "   The new web app replaces it at every start. Restart it and run this script again:"
        echo "     sudo docker restart nettap-web"
        echo "     bash $REPO_DIR/scripts/remote/deploy-change-password.sh"
    fi
fi
echo ""

if [ "$ACCOUNTS" -gt 0 ]; then
    echo "→ Step 7: Signed-in checks (a 60 s session from mint-session.cjs, never printed)..."
    # {} changes no credential: the handler itself answers 400 with its exact sentence
    OUT=$(signed_in --max-time 20 -w '\n%{http_code}' -X POST -H 'Content-Type: application/json' --data '{}' "$BASE/api/account/password")
    CODE=${OUT##*$'\n'}
    if [ "$CODE" = "400" ] && printf '%s' "$OUT" | grep -qF "$EMPTY_FORM"; then rc=0; else rc=1; fi
    check "signed-in POST {} reaches the handler: 400 and \"Enter your current password and a new one.\"" "$rc" "$CODE"
    check_eq "a minted session works: /api/auth/me" "$(signed_in -o /dev/null --max-time 20 -w '%{http_code}' "$BASE/api/auth/me")" 200
    for path in "/" "/traffic/streaming?range=1h" "/reports" "/settings?tab=notifications"; do
        LOC=$(redirect_of "$path")
        case "$LOC" in "302 "*"/login"*) rc=0 ;; *) rc=1 ;; esac
        check "$path signed out goes to /login" "$rc" "$LOC"
    done
else
    echo "→ Step 7: First-run checks (no account yet; the store must stay empty)..."
    # OLD CODE START — NET-358 review: the NETTAP_SESSION_SECRET override is gone, so jwt-secret-v2.txt is always needed
    # if web_env_has NETTAP_SESSION_SECRET; then
    #     echo "   ✓ NETTAP_SESSION_SECRET is set: no jwt-secret-v2.txt is needed"
    # else
    # OLD CODE END
    V2=$(key_state jwt-secret-v2.txt)
    if [ "${V2%%:*}" = "ok" ]; then rc=0; else rc=1; fi
    check "jwt-secret-v2.txt exists and is valid" "$rc" "${V2%%:*}"
    LOC=$(redirect_of "/")
    case "$LOC" in "302 "*"/setup"*) rc=0 ;; *) rc=1 ;; esac
    check "/ goes to /setup" "$rc" "$LOC"
    check_eq "users.json still holds no account" "$(account_count)" 0
fi
echo ""

echo "→ Step 8: Log errors since the restart..."
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
fi
echo "Everyone signs in again once: sessions from before this deploy no longer work."
echo "To see it: sign in, open Settings › Account, and change the password once."
if [ "$LEGACY_REPLACED" -eq 1 ]; then
    echo "To go back to the web image from before the first run: bash $REPO_DIR/scripts/remote/rollback-change-password.sh"
elif [ "$WEB" != "healthy" ]; then
    echo "Before rolling back, read sudo docker logs nettap-web --tail 50: Step 6 says when rolling back is safe."
else
    echo "Don't roll back until jwt-secret.txt is replaced: sudo docker restart nettap-web, then run this script again."
fi
exit "$FAILED"
