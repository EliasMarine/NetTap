#!/usr/bin/env bash
# Runs ON nginx-local as root: website/deploy.sh feeds it over ssh. It never touches another site's files.
#   deploy <release>  make /var/www/nettap.dev/releases/<release> live with the conf uploaded to /root/nettap.dev.conf.new
#   rollback          serve the live release's recorded predecessor again
# Any failure while deploying puts the vhost, its symlink and the "current" release back as they were.
set -uo pipefail
trap '' HUP PIPE # a dropped ssh session must not stop us between a change and its restore

BASE=/var/www/nettap.dev
AVAIL=/etc/nginx/sites-available/nettap.dev
ENABLED=/etc/nginx/sites-enabled/nettap.dev
NEW_CONF=/root/nettap.dev.conf.new
BOOT_CONF=/root/nettap.dev.bootstrap.conf
CERT=/etc/letsencrypt/live/nettap.dev/fullchain.pem
RENEWAL=/etc/letsencrypt/renewal/nettap.dev.conf
BAK=/root/nettap.dev.nginx.bak-$(date -u +%Y%m%dT%H%M%SZ)
SNAPPED=0

say() { echo "→ $*"; }
ok() { echo "   ✓ $*"; }
die() { echo "✗ $*" >&2; exit 1; }

# Every server_name on the box except ours.
other_sites() {
  nginx -T 2>/dev/null |
    awk '$1 == "server_name" { for (i = 2; i <= NF; i++) { n = $i; if (n ~ /^#/) break; sub(/;$/, "", n); print n } }' |
    grep -v -e '^_$' -e '^$' -e 'nettap\.dev$' | sort -u
}

# How each other site answers right now, over http and https, from this box.
baseline() {
  local name scheme
  for name in $(other_sites); do
    for scheme in http https; do
      printf '%s://%s %s\n' "$scheme" "$name" "$(curl -sk -m 10 -o /dev/null -w '%{http_code} %{redirect_url}' \
        --resolve "$name:80:127.0.0.1" --resolve "$name:443:127.0.0.1" "$scheme://$name/")"
    done
  done
}

point_current() { # $1 = absolute release dir, or "none"
  if [ "$1" = none ]; then
    rm -f "$BASE/current"
  else
    ln -sfn "$1" "$BASE/current.tmp" && mv -T "$BASE/current.tmp" "$BASE/current"
  fi
}

# check <url> <status> [text...]: the status must match and each text must appear in the headers or body.
check() {
  local url=$1 want=$2 out code text
  shift 2
  for _ in 1 2 3 4 5; do # a reload reaches new workers a moment after systemctl returns
    out=$(curl -s -m 10 -D - --resolve nettap.dev:80:127.0.0.1 --resolve nettap.dev:443:127.0.0.1 \
      --resolve www.nettap.dev:80:127.0.0.1 --resolve www.nettap.dev:443:127.0.0.1 "$url") || true
    code=$(printf '%s\n' "$out" | awk 'NR == 1 { print $2 }')
    [ "$code" = "$want" ] && break
    sleep 1
  done
  [ "$code" = "$want" ] || { echo "✗ $url answered ${code:-nothing}, expected $want" >&2; return 1; }
  for text in "$@"; do
    grep -qiF -- "$text" <<< "$out" || { echo "✗ $url is missing: $text" >&2; return 1; }
  done
  ok "$url $code"
}

verify() { # $1 = the release that must be answering
  check https://nettap.dev/ 200 "name=\"nettap-release\" content=\"$1\"" "content-security-policy: default-src 'self'" \
    'strict-transport-security: max-age=31536000' &&
    check https://nettap.dev/features 200 "content=\"$1\"" &&
    check https://nettap.dev/hero.js 200 &&
    check https://nettap.dev/nope 404 'This page isn' &&
    check https://nettap.dev/a/b/c 404 'This page isn' &&
    check 'http://nettap.dev/x?y=1' 301 'location: https://nettap.dev/x?y=1' &&
    check http://www.nettap.dev/ 301 'location: https://nettap.dev/' &&
    check https://www.nettap.dev/x 301 'location: https://nettap.dev/x'
}

cert_ok() {
  grep -q '^authenticator = webroot' "$RENEWAL" &&
    grep -q '^renew_hook = systemctl reload nginx' "$RENEWAL" &&
    grep -q '^nettap.dev = /var/www/letsencrypt' "$RENEWAL" &&
    grep -q '^www.nettap.dev = /var/www/letsencrypt' "$RENEWAL" &&
    systemctl is-active --quiet certbot.timer
}

# Put the vhost file, its symlink and "current" back as the snapshot found them, drop the candidate, stop.
fail() {
  echo "✗ $*" >&2
  if [ "$SNAPPED" = 1 ]; then
    say "Putting nettap.dev back the way it was"
    if [ "$HAD_AVAIL" = 1 ]; then cp -p "$BAK" "$AVAIL"; else rm -f "$AVAIL"; fi
    if [ "$HAD_ENABLED" = 1 ]; then ln -sfn "$AVAIL" "$ENABLED"; else rm -f "$ENABLED"; fi
    point_current "$PREV"
    if nginx -tq && systemctl reload nginx; then
      ok "restored"
    else
      echo "✗ nginx -t still fails after the restore. Fix it by hand (backup: $BAK)" >&2
    fi
  fi
  rm -rf "${REL_DIR:?}"
  exit 1
}

apply_conf() { # $1 = the conf to make live
  cp "$1" "$AVAIL" && ln -sfn "$AVAIL" "$ENABLED" && nginx -tq && systemctl reload nginx ||
    fail "nginx rejected $1"
  ok "nginx accepted $1"
}

prune() { # keep the live release, its predecessor and the last 3 successful ones
  local keep d
  keep=$({
    echo "$REL"
    awk -v r="$REL" '$1 == r { print $2 }' "$BASE/history"
    tail -n 3 "$BASE/history" | awk '{ print $1 }'
  } | sort -u)
  for d in "$BASE"/releases/*/; do
    d=${d%/}
    printf '%s\n' "$keep" | grep -qxF "$(basename "$d")" || { rm -rf "$d"; ok "pruned $(basename "$d")"; }
  done
}

deploy() {
  REL=$1
  [[ $REL =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7,40}(-dirty)?$ ]] || die "bad release name: $REL"
  REL_DIR=$BASE/releases/$REL
  for f in index.html features.html 404.html hero.js; do
    [ -f "$REL_DIR/$f" ] || fail "release $REL has no $f"
  done
  [ -f "$NEW_CONF" ] || fail "no $NEW_CONF uploaded"
  find "$REL_DIR" -type d -exec chmod 755 {} +
  find "$REL_DIR" -type f -exec chmod 644 {} +

  say "Preflight"
  local conflicts before after
  nginx -tq || fail "nginx -t fails before any change: fix that first"
  conflicts=$(grep -Rl 'nettap\.dev' /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | grep -vxF "$ENABLED")
  [ -z "$conflicts" ] || fail "another nginx file already names nettap.dev: $conflicts"
  grep -q 'listen 80 default_server' /etc/nginx/sites-enabled/000-default &&
    grep -Eq 'listen 443 .*default_server' /etc/nginx/sites-enabled/000-default ||
    fail "000-default no longer holds default_server on 80 and 443"
  before=$(baseline)
  [ -n "$before" ] || fail "found no other sites to compare against"
  ok "nginx -t passes, no name clash, $(printf '%s\n' "$before" | wc -l) answers from the other sites recorded"

  say "Snapshot"
  HAD_AVAIL=0 HAD_ENABLED=0
  if [ -f "$AVAIL" ]; then HAD_AVAIL=1; cp -p "$AVAIL" "$BAK"; fi
  [ -L "$ENABLED" ] && HAD_ENABLED=1
  PREV=$(readlink "$BASE/current" 2>/dev/null || echo none)
  SNAPPED=1
  ok "conf=$HAD_AVAIL enabled=$HAD_ENABLED current=$(basename "$PREV")"

  if [ ! -f "$CERT" ]; then
    say "First certificate (webroot)"
    sed -n '/^# BEGIN http/,/^# END http/p' "$NEW_CONF" > "$BOOT_CONF"
    apply_conf "$BOOT_CONF"
    certbot certonly --webroot -w /var/www/letsencrypt -d nettap.dev -d www.nettap.dev \
      --non-interactive --agree-tos --deploy-hook 'systemctl reload nginx' ||
      fail "certbot could not get a certificate: check the A record for nettap.dev and the CNAME for www"
  fi

  say "nginx vhost"
  apply_conf "$NEW_CONF"

  say "Go live: $REL"
  point_current "$REL_DIR" || fail "couldn't switch current to $REL"
  verify "$REL" || fail "nettap.dev didn't answer as expected"
  after=$(baseline)
  if [ "$after" != "$before" ]; then
    diff <(printf '%s\n' "$before") <(printf '%s\n' "$after") >&2
    fail "another site's answer changed"
  fi
  ok "every other site answers as before"

  say "Certificate renewal"
  cert_ok || fail "renewal settings in $RENEWAL aren't webroot + reload hook, or certbot.timer is off"
  if [ "$PREV" = none ]; then
    certbot renew --dry-run --cert-name nettap.dev --run-deploy-hooks -q || fail "the renewal dry run failed"
    systemctl is-active --quiet nginx || fail "nginx isn't running after the dry run"
    ok "renewal dry run passed and nginx reloaded"
  fi
  ok "webroot renewal with a reload hook; certbot.timer active"

  echo "$REL $(basename "$PREV")" >> "$BASE/history"
  prune
  rm -f "$NEW_CONF" "$BOOT_CONF" "$BAK"
  ok "nettap.dev serves $REL"
}

rollback() {
  local cur pred
  cur=$(basename "$(readlink "$BASE/current" 2>/dev/null || echo none)")
  pred=$(awk -v c="$cur" '$1 == c { p = $2 } END { print p }' "$BASE/history" 2>/dev/null)
  [ -n "$pred" ] && [ "$pred" != none ] && [ -d "$BASE/releases/$pred" ] || die "no earlier release recorded for $cur"
  say "Rolling back: $cur → $pred"
  point_current "$BASE/releases/$pred" || die "couldn't switch current"
  if verify "$pred"; then
    ok "nettap.dev serves $pred"
  else
    point_current "$BASE/releases/$cur"
    die "$pred didn't verify, so $cur is live again"
  fi
}

case "${1:-}" in
  deploy) deploy "${2:-}" ;;
  rollback) rollback ;;
  *) die "usage: deploy-remote.sh deploy <release> | rollback" ;;
esac
