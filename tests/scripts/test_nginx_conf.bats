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
