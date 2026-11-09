#!/usr/bin/env bats
# ==========================================================================
# BATS tests for docker/nginx.conf
# ==========================================================================
# Structural checks: tools that reach stored traffic data must sit behind
# NetTap's login, and must never trust identity headers from the client.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
NGINX_CONF="${REPO_ROOT}/docker/nginx.conf"

# Print one live (uncommented) location block, e.g. _location '/dashboards/'
_location() {
    grep -v '^[[:space:]]*#' "$NGINX_CONF" | awk -v loc="location $1 {" '
        index($0, loc) { inside = 1 }
        inside { print; if ($0 ~ /^[[:space:]]*}[[:space:]]*$/) exit }
    '
}

@test "nginx: session check location is internal and asks SvelteKit" {
    run _location '= /_nettap_auth'
    [ "$status" -eq 0 ]
    echo "$output" | grep -q 'internal;'
    echo "$output" | grep -q 'proxy_pass http://sveltekit/api/auth/me;'
}

@test "nginx: /dashboards/ requires a NetTap login (CR-003)" {
    run _location '/dashboards/'
    echo "$output" | grep -q 'auth_request /_nettap_auth;'
    echo "$output" | grep -q 'error_page 401 = @nettap_login;'
}

@test "nginx: /dashboards/ sets identity only from the session (CR-003)" {
    run _location '/dashboards/'
    echo "$output" | grep -q 'proxy_set_header X-Forwarded-User  \$nettap_user;'
    echo "$output" | grep -q 'proxy_set_header X-Forwarded-Roles \$nettap_role;'
}

@test "nginx: /grafana/ requires a NetTap login (CR-022)" {
    run _location '/grafana/'
    echo "$output" | grep -q 'auth_request /_nettap_auth;'
    echo "$output" | grep -q 'error_page 401 = @nettap_login;'
}

@test "nginx: /cyberchef/ requires a NetTap login (NET-229)" {
    run _location '/cyberchef/'
    echo "$output" | grep -q 'auth_request /_nettap_auth;'
    echo "$output" | grep -q 'error_page 401 = @nettap_login;'
}

@test "nginx: CSP lets same-origin blob Web Workers run (CyberChef)" {
    # CyberChef inlines its workers as blob: URLs; without worker-src they fall back to
    # script-src and are blocked, so CyberChef never leaves its loading screen
    csp=$(grep -v '^\s*#' "$NGINX_CONF" | grep 'add_header Content-Security-Policy')
    echo "$csp" | grep -q "worker-src 'self' blob:"
}

@test "nginx: response header buffer fits SvelteKit's Link header (NET-223)" {
    # Home's Link header was 4.5 KB; at the 4 KB default every logged-in reload was a 502
    live=$(grep -v '^[[:space:]]*#' "$NGINX_CONF")
    echo "$live" | grep -Eq '^[[:space:]]*proxy_buffer_size 16k;'
    echo "$live" | grep -Eq '^[[:space:]]*proxy_buffers 8 16k;'
}

@test "nginx: every upstream re-resolves a recreated container's IP (#138)" {
    # resolved once at startup, a recreated nettap-web's new IP made every page a 502
    live=$(grep -v '^[[:space:]]*#' "$NGINX_CONF")
    echo "$live" | grep -Eq '^[[:space:]]*resolver 127\.0\.0\.11 valid=10s'
    servers=$(echo "$live" | grep -Ec '^[[:space:]]*server nettap-[a-z-]+:[0-9]+')
    resolved=$(echo "$live" | grep -Ec '^[[:space:]]*server nettap-[a-z-]+:[0-9]+ resolve;')
    zones=$(echo "$live" | grep -Ec '^[[:space:]]*zone [a-z]+ 64k;')
    [ "$servers" -eq 3 ] && [ "$resolved" -eq 3 ] && [ "$zones" -eq 3 ]
    # "resolve" needs nginx 1.27.3+: the image is pinned, not a floating tag
    grep -Eq '^[[:space:]]*image: nginx:1\.(2[89]|[3-9][0-9])-alpine$' "${REPO_ROOT}/docker/docker-compose.yml"
}

@test "nginx: /grafana/ keeps its path and starts without Grafana (#71)" {
    run _location '/grafana/'
    [ "$status" -eq 0 ]
    # The full /grafana/... path reaches Grafana (it serves from that sub-path)
    echo "$output" | grep -Eq '^[[:space:]]*proxy_pass \$grafana_upstream;'
    ! echo "$output" | grep -Eq '^[[:space:]]*proxy_pass http://grafana/;'
    # Resolved per request, so a missing container can't stop nginx starting
    echo "$output" | grep -Eq '^[[:space:]]*resolver 127\.0\.0\.11'
    ! grep -Eq '^[[:space:]]*upstream grafana' "$NGINX_CONF"
}
