#!/usr/bin/env bash
# ==========================================================================
# Fake docker for deploy-malcolm.sh's OpenSearch bootstrap (NET-217)
# ==========================================================================
# Sourced after scripts/install/deploy-malcolm.sh inside a test's `bash -c`.
# It plays dashboards-helper and opensearch: every curl call's argv goes to
# ${TEST_TMPDIR}/curl.log (one line each) and bodies sent on stdin go to
# ${TEST_TMPDIR}/body.<last path segment>. The scenario comes from F_* variables:
#   F_MT_GET           keep-check read of malcolm_template: 404 (default), 200, 401, 500, transport
#   F_MT_BODY          its body when 200 (default: a template targeting arkime_sessions3-*)
#   F_MT_PUT           codes for successive malcolm_template PUTs, the last repeats (default 200)
#   F_COMP_FAIL        component template name whose PUT answers 500
#   F_NO_FILES         set: dashboards-helper lists no component template files
#   F_MARKER_PUT       code for the create-only marker PUT (default 200)
#   F_MARKER_PRESENT   0: the acceptance GET of arkime_sessions3_template fails (default 1)
#   F_AUTH_OK_AFTER    number of failed auth probes before they pass, or "never" (default 0)
#   F_SECADMIN_RC      exit code of securityadmin.sh (default 0)

F_MT_GET="${F_MT_GET:-404}"
if [[ -z "${F_MT_BODY:-}" ]]; then
    F_MT_BODY='{"index_templates":[{"index_template":{"index_patterns":["arkime_sessions3-*"]}}]}'
fi
F_MT_PUT="${F_MT_PUT:-200}"
F_MARKER_PUT="${F_MARKER_PUT:-200}"
F_MARKER_PRESENT="${F_MARKER_PRESENT:-1}"
F_AUTH_OK_AFTER="${F_AUTH_OK_AFTER:-0}"
F_SECADMIN_RC="${F_SECADMIN_RC:-0}"

sleep() { :; }

_f_count() {  # _f_count NAME: bump and print a call counter
    local f="${TEST_TMPDIR}/count.$1" n=0
    [[ -f "$f" ]] && n=$(cat "$f")
    n=$((n + 1))
    echo "$n" > "$f"
    echo "$n"
}

_f_nth() {  # _f_nth N "c1 c2 ...": the Nth code, the last one repeating
    local n="$1" codes
    read -r -a codes <<< "$2"
    if (( n > ${#codes[@]} )); then n=${#codes[@]}; fi
    echo "${codes[n - 1]}"
}

_fake_curl() {
    echo "curl $*" >> "${TEST_TMPDIR}/curl.log"
    local method=GET url="" fmt="" data="" out="" fail=false
    while (( $# )); do
        case "$1" in
            -X) method="$2"; shift ;;
            -w) fmt="$2"; shift ;;
            -d) data="$2"; shift ;;
            -o) out="$2"; shift ;;
            --fail) fail=true ;;
            https://*) url="$1" ;;
        esac
        shift
    done
    local path="${url#https://opensearch:9200/}" code=200 body="{}"
    path="${path%%\?*}"
    if [[ "$data" == "@-" ]]; then cat > "${TEST_TMPDIR}/body.${path##*/}"; fi

    case "$method $path" in
        "GET _index_template/malcolm_template")
            if [[ "$url" == *filter_path* ]]; then
                [[ "$F_MT_GET" == transport ]] && { printf '000'; return 28; }
                code="$F_MT_GET"; body="$F_MT_BODY"
            elif [[ -f "${TEST_TMPDIR}/count.mt_put" || "$F_MT_GET" == 200 ]]; then
                code=200
            else
                code=404
            fi ;;
        "PUT _index_template/malcolm_template") code=$(_f_nth "$(_f_count mt_put)" "$F_MT_PUT") ;;
        "PUT _component_template/"*) [[ "${path##*/}" == "${F_COMP_FAIL:-}" ]] && code=500 ;;
        "PUT _template/arkime_sessions3_template") code="$F_MARKER_PUT" ;;
        "GET _template/arkime_sessions3_template") [[ "$F_MARKER_PRESENT" == 1 ]] || code=404 ;;
    esac

    if [[ "$fail" == true && "$code" -ge 400 ]]; then return 22; fi
    if [[ "$out" != /dev/null ]]; then printf '%s' "$body"; fi
    if [[ -n "$fmt" ]]; then printf '%b' "${fmt//%\{http_code\}/$code}"; fi
    return 0
}

_fake_opensearch() {  # args after "exec -T opensearch"
    case "$*" in
        *securityadmin*)
            echo "securityadmin $*" >> "${TEST_TMPDIR}/securityadmin.log"
            return "$F_SECADMIN_RC" ;;
        curl*_cluster/health*)
            echo "auth $*" >> "${TEST_TMPDIR}/auth.log"
            local n
            n=$(_f_count auth)
            [[ "$F_AUTH_OK_AFTER" != never ]] && (( n > F_AUTH_OK_AFTER )) ;;
        *) echo "unexpected opensearch exec: $*" >&2; return 99 ;;
    esac
}

docker() {
    # docker compose -f FILE <subcommand> ...
    [[ "$1" == compose && "$2" == -f ]] || { echo "unexpected docker $*" >&2; return 99; }
    shift 3
    case "$1 ${2:-} ${3:-}" in
        "up -d dashboards-helper") echo "up dashboards-helper" >> "${TEST_TMPDIR}/up.log"; return 0 ;;
        "exec -T opensearch") shift 3; _fake_opensearch "$@"; return ;;
        "exec -T dashboards-helper") shift 3 ;;
        *) echo "unexpected docker compose $*" >&2; return 99 ;;
    esac
    case "$1" in
        curl) shift; _fake_curl "$@" ;;
        jq) shift; command jq "$@" ;;
        find)
            [[ -n "${F_NO_FILES:-}" ]] && return 0
            case "$2" in
                /opt/ecs-templates-os/*) printf '%s\n' "$2/base.json" "$2/event.json" ;;
                *) printf '%s\n' "$2/zeek.json" ;;
            esac ;;
        cat) echo '{"index_patterns":["MALCOLM_NETWORK_INDEX_PATTERN_REPLACER"],"composed_of":["ecs_base"]}' ;;
        *) echo "unexpected dashboards-helper exec: $*" >&2; return 99 ;;
    esac
}
