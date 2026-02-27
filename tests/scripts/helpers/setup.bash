#!/usr/bin/env bash
# ==========================================================================
# BATS test helper — common setup for NetTap script tests
# ==========================================================================
# Sourced by test files via: load 'helpers/setup'
#
# Provides:
#   - Temporary directory for each test
#   - Override of common.sh functions for testing
#   - Mock infrastructure via helpers/mocks.bash

# Create a temp directory for each test
setup() {
    TEST_TMPDIR="$(mktemp -d)"
    export TEST_TMPDIR

    # Create a minimal .env.example for tests
    cat > "${TEST_TMPDIR}/.env.example" <<'EOF'
NETTAP_HOSTNAME=nettap.local
DASHBOARD_PORT=443
OPENSEARCH_JAVA_OPTS="-Xms4g -Xmx4g"
RETENTION_HOT=90
EOF

    # Set PROJECT_ROOT to the temp directory so scripts write there
    export PROJECT_ROOT="${TEST_TMPDIR}"

    # Source mocks
    load 'helpers/mocks'
}

teardown() {
    if [[ -d "${TEST_TMPDIR:-}" ]]; then
        rm -rf "$TEST_TMPDIR"
    fi
}
