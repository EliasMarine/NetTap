#!/usr/bin/env bash
# NetTap — v1.0 Release Verification Suite
# Runs a comprehensive set of checks to verify release readiness.
#
# Usage:
#   ./scripts/verify-release.sh [OPTIONS]
#
# Options:
#   --quick          Checks 1-7 only (no Docker builds, CVE scan, or E2E)
#   --full           All checks including Docker builds, Trivy scan, E2E (default)
#   --docker         Quick checks + Docker image builds
#   --trivy          Quick checks + Docker builds + Trivy CVE scan
#   --secrets-only   Run only the secrets audit
#   -v, --verbose    Show full command output (not just pass/fail)
#   -h, --help       Show this help message

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source shared utilities for logging and colors
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODE="full"    # quick | full | docker | trivy | secrets-only
VERBOSE=false
TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_SKIP=0

# Section results for summary table
declare -a SECTION_NAMES=()
declare -a SECTION_RESULTS=()
declare -a SECTION_TIMES=()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_bold=$'\033[1m'
_dim=$'\033[2m'

pass() {
    TOTAL_PASS=$((TOTAL_PASS + 1))
    echo "  ${_CLR_GRN}PASS${_CLR_RST} $*"
}

fail() {
    TOTAL_FAIL=$((TOTAL_FAIL + 1))
    echo "  ${_CLR_RED}FAIL${_CLR_RST} $*" >&2
}

skip() {
    TOTAL_SKIP=$((TOTAL_SKIP + 1))
    echo "  ${_dim}SKIP${_CLR_RST} $*"
}

section_start() {
    local name="$1"
    SECTION_NAMES+=("$name")
    _SECTION_START=$(date +%s)
    echo ""
    echo "${_bold}[$((${#SECTION_NAMES[@]}))/${TOTAL_SECTIONS}] ${name}${_CLR_RST}"
    echo "────────────────────────────────────────"
}

section_end() {
    local result="$1"
    local elapsed=$(( $(date +%s) - _SECTION_START ))
    SECTION_RESULTS+=("$result")
    SECTION_TIMES+=("${elapsed}s")
}

run_cmd() {
    local desc="$1"
    shift
    if [[ "$VERBOSE" == "true" ]]; then
        if "$@"; then
            pass "$desc"
            return 0
        else
            fail "$desc"
            return 1
        fi
    else
        local output
        if output=$("$@" 2>&1); then
            pass "$desc"
            return 0
        else
            fail "$desc"
            echo "    ${_dim}${output:0:500}${_CLR_RST}" >&2
            return 1
        fi
    fi
}

usage() {
    head -n 16 "${BASH_SOURCE[0]}" | tail -n +2 | sed 's/^# \?//'
    exit 0
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --quick)        MODE="quick"; shift ;;
        --full)         MODE="full"; shift ;;
        --docker)       MODE="docker"; shift ;;
        --trivy)        MODE="trivy"; shift ;;
        --secrets-only) MODE="secrets-only"; shift ;;
        -v|--verbose)   VERBOSE=true; shift ;;
        -h|--help)      usage ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            ;;
    esac
done

# Determine which sections to run
RUN_SECRETS=true
RUN_LINT=true
RUN_TESTS=true
RUN_DOCKER=false
RUN_TRIVY=false
RUN_E2E=false

case "$MODE" in
    quick)
        TOTAL_SECTIONS=8  # 1-7 + summary
        ;;
    docker)
        RUN_DOCKER=true
        TOTAL_SECTIONS=9
        ;;
    trivy)
        RUN_DOCKER=true
        RUN_TRIVY=true
        TOTAL_SECTIONS=10
        ;;
    full)
        RUN_DOCKER=true
        RUN_TRIVY=true
        RUN_E2E=true
        TOTAL_SECTIONS=12  # all 11 + summary
        ;;
    secrets-only)
        RUN_LINT=false
        RUN_TESTS=false
        TOTAL_SECTIONS=2  # secrets + summary
        ;;
esac

OVERALL_START=$(date +%s)

echo ""
echo "${_bold}NetTap v1.0 Release Verification${_CLR_RST}"
echo "Mode: ${MODE} | Verbose: ${VERBOSE}"
echo "Project: ${PROJECT_ROOT}"
echo "========================================"

cd "$PROJECT_ROOT"

# =========================================================================
# 1. Secrets Audit
# =========================================================================
section_start "Secrets Audit"
SECTION_OK=true

# Check for common secret patterns in tracked files
SECRETS_PATTERN='(password|secret|api_key|token|private_key)\s*[:=]\s*["\x27][^"\x27]{8,}'
if git ls-files | xargs grep -ilE "$SECRETS_PATTERN" 2>/dev/null | grep -v -E '\.(md|test\.|spec\.|example|sample|CLAUDE)' | grep -v 'node_modules' | head -20 | grep -q .; then
    fail "Potential secrets found in tracked files:"
    git ls-files | xargs grep -ilE "$SECRETS_PATTERN" 2>/dev/null | grep -v -E '\.(md|test\.|spec\.|example|sample|CLAUDE)' | grep -v 'node_modules' | head -10 | while read -r f; do echo "    - $f"; done
    SECTION_OK=false
else
    pass "No hardcoded secrets in tracked files"
fi

# Verify .env files are gitignored
if git ls-files --cached | grep -qE '\.env($|\.)'; then
    fail ".env file(s) tracked by git"
    SECTION_OK=false
else
    pass ".env files excluded from git"
fi

# Check docker/.env is gitignored
if [[ -f docker/.env ]] && git check-ignore -q docker/.env 2>/dev/null; then
    pass "docker/.env is gitignored"
elif [[ ! -f docker/.env ]]; then
    pass "docker/.env does not exist (secrets generated at deploy time)"
else
    fail "docker/.env exists but is NOT gitignored"
    SECTION_OK=false
fi

if [[ "$SECTION_OK" == "true" ]]; then
    section_end "PASS"
else
    section_end "FAIL"
fi

if [[ "$MODE" == "secrets-only" ]]; then
    # Skip to summary
    RUN_LINT=false
    RUN_TESTS=false
fi

# =========================================================================
# 2. Python Lint (ruff)
# =========================================================================
if [[ "$RUN_LINT" == "true" ]]; then
    section_start "Python Lint"
    SECTION_OK=true

    if command -v ruff &>/dev/null; then
        run_cmd "ruff check (linting)" ruff check daemon/ || SECTION_OK=false
        run_cmd "ruff format --check (formatting)" ruff format --check daemon/ || SECTION_OK=false
    else
        skip "ruff not installed (pip install ruff)"
    fi

    if [[ "$SECTION_OK" == "true" ]]; then
        section_end "PASS"
    else
        section_end "FAIL"
    fi

    # =========================================================================
    # 3. Shell Lint (shellcheck)
    # =========================================================================
    section_start "Shell Lint"
    SECTION_OK=true

    if command -v shellcheck &>/dev/null; then
        SHELL_FILES=$(find scripts/ -name '*.sh' -type f 2>/dev/null || true)
        if [[ -n "$SHELL_FILES" ]]; then
            # shellcheck disable=SC2086
            run_cmd "shellcheck scripts/**/*.sh" shellcheck $SHELL_FILES || SECTION_OK=false
        else
            skip "No shell scripts found in scripts/"
        fi
    else
        skip "shellcheck not installed (brew install shellcheck / apt install shellcheck)"
    fi

    if [[ "$SECTION_OK" == "true" ]]; then
        section_end "PASS"
    else
        section_end "FAIL"
    fi
fi

# =========================================================================
# 4. Python Tests (pytest)
# =========================================================================
if [[ "$RUN_TESTS" == "true" ]]; then
    section_start "Python Tests"
    SECTION_OK=true

    if command -v python3 &>/dev/null && [[ -d daemon/tests ]]; then
        run_cmd "pytest daemon/tests/" python3 -m pytest daemon/tests/ -v --tb=short || SECTION_OK=false
    else
        skip "python3 or daemon/tests/ not available"
    fi

    if [[ "$SECTION_OK" == "true" ]]; then
        section_end "PASS"
    else
        section_end "FAIL"
    fi

    # =========================================================================
    # 5. Web Dependencies (npm ci)
    # =========================================================================
    section_start "Web Dependencies"
    SECTION_OK=true

    if [[ -d web ]] && command -v npm &>/dev/null; then
        run_cmd "npm ci" bash -c "cd web && npm ci" || SECTION_OK=false
    else
        skip "web/ directory or npm not available"
    fi

    if [[ "$SECTION_OK" == "true" ]]; then
        section_end "PASS"
    else
        section_end "FAIL"
    fi

    # =========================================================================
    # 6. Web Type Check (svelte-check)
    # =========================================================================
    section_start "Web Type Check"
    SECTION_OK=true

    if [[ -d web/node_modules ]]; then
        run_cmd "svelte-check --threshold error" bash -c "cd web && npx svelte-check --threshold error" || SECTION_OK=false
    else
        skip "web/node_modules missing (run npm ci first)"
    fi

    if [[ "$SECTION_OK" == "true" ]]; then
        section_end "PASS"
    else
        section_end "FAIL"
    fi

    # =========================================================================
    # 7. Web Unit Tests (vitest)
    # =========================================================================
    section_start "Web Unit Tests"
    SECTION_OK=true

    if [[ -d web/node_modules ]]; then
        run_cmd "vitest run" bash -c "cd web && npx vitest run" || SECTION_OK=false
    else
        skip "web/node_modules missing (run npm ci first)"
    fi

    if [[ "$SECTION_OK" == "true" ]]; then
        section_end "PASS"
    else
        section_end "FAIL"
    fi
fi

# =========================================================================
# 8. Docker Builds
# =========================================================================
if [[ "$RUN_DOCKER" == "true" ]]; then
    section_start "Docker Builds"
    SECTION_OK=true

    if command -v docker &>/dev/null; then
        COMPOSE_FILE="docker/docker-compose.yml"
        if [[ -f "$COMPOSE_FILE" ]]; then
            for svc in nettap-storage-daemon nettap-web nettap-tshark nettap-cyberchef; do
                run_cmd "Build ${svc}" docker compose -f "$COMPOSE_FILE" build "$svc" || SECTION_OK=false
            done
        else
            fail "docker-compose.yml not found at ${COMPOSE_FILE}"
            SECTION_OK=false
        fi
    else
        skip "docker not installed"
    fi

    if [[ "$SECTION_OK" == "true" ]]; then
        section_end "PASS"
    else
        section_end "FAIL"
    fi
fi

# =========================================================================
# 9. Trivy CVE Scan
# =========================================================================
if [[ "$RUN_TRIVY" == "true" ]]; then
    section_start "Trivy CVE Scan"
    SECTION_OK=true

    if command -v trivy &>/dev/null; then
        for img in nettap-storage-daemon nettap-web; do
            run_cmd "Scan ${img} (CRITICAL/HIGH)" trivy image --severity CRITICAL,HIGH --exit-code 1 "${img}:latest" || SECTION_OK=false
        done
    else
        skip "trivy not installed (brew install trivy / see https://trivy.dev)"
    fi

    if [[ "$SECTION_OK" == "true" ]]; then
        section_end "PASS"
    else
        section_end "FAIL"
    fi
fi

# =========================================================================
# 10. E2E Tests (Playwright)
# =========================================================================
if [[ "$RUN_E2E" == "true" ]]; then
    section_start "E2E Tests (Playwright)"
    SECTION_OK=true

    if [[ -f web/playwright.config.ts ]] && [[ -d web/node_modules ]]; then
        run_cmd "playwright test" bash -c "cd web && npx playwright test" || SECTION_OK=false
    else
        skip "Playwright not configured or node_modules missing"
    fi

    if [[ "$SECTION_OK" == "true" ]]; then
        section_end "PASS"
    else
        section_end "FAIL"
    fi
fi

# =========================================================================
# 11. Summary
# =========================================================================
OVERALL_ELAPSED=$(( $(date +%s) - OVERALL_START ))

echo ""
echo "${_bold}========================================"
echo "  Release Verification Summary"
echo "========================================${_CLR_RST}"
echo ""

# Print results table
printf "  %-4s %-30s %-8s %s\n" "#" "Check" "Result" "Time"
printf "  %-4s %-30s %-8s %s\n" "---" "------------------------------" "------" "----"

for i in "${!SECTION_NAMES[@]}"; do
    local_result="${SECTION_RESULTS[$i]}"
    if [[ "$local_result" == "PASS" ]]; then
        color="${_CLR_GRN}"
    elif [[ "$local_result" == "FAIL" ]]; then
        color="${_CLR_RED}"
    else
        color="${_dim}"
    fi
    printf "  %-4s %-30s ${color}%-8s${_CLR_RST} %s\n" "$((i+1))" "${SECTION_NAMES[$i]}" "${local_result}" "${SECTION_TIMES[$i]}"
done

echo ""
echo "  ${_CLR_GRN}Passed: ${TOTAL_PASS}${_CLR_RST}  |  ${_CLR_RED}Failed: ${TOTAL_FAIL}${_CLR_RST}  |  ${_dim}Skipped: ${TOTAL_SKIP}${_CLR_RST}"
echo "  Total time: ${OVERALL_ELAPSED}s"
echo ""

if [[ "$TOTAL_FAIL" -gt 0 ]]; then
    echo "  ${_CLR_RED}${_bold}RELEASE NOT READY${_CLR_RST} — fix ${TOTAL_FAIL} failing check(s) above"
    echo ""
    exit 1
else
    echo "  ${_CLR_GRN}${_bold}ALL CHECKS PASSED${_CLR_RST} — release is ready!"
    echo ""
    exit 0
fi
