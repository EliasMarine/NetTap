#!/usr/bin/env bats
# NET-243: config/filebeat/flush-timeout.sh sets Filebeat's queue flush timeout, then always
# starts the image's own entrypoint, even when the patch fails (slower alerts, never no data).

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/config/filebeat/flush-timeout.sh"

setup() {
    STUBS="$(mktemp -d)"
    export YQ_ARGS="${STUBS}/yq.args"
}

teardown() {
    rm -rf "$STUBS"
}

stub_yq() {
    printf '#!/bin/bash\nprintf "%%s\\n" "$@" > "%s"\nexit %s\n' "$YQ_ARGS" "$1" > "${STUBS}/yq"
    chmod +x "${STUBS}/yq"
}

@test "flush-timeout: sets 2 s in the image's filebeat-logs.yml, then runs the entrypoint" {
    stub_yq 0
    run env PATH="${STUBS}:/usr/bin:/bin" bash "$SCRIPT" echo started
    [ "$status" -eq 0 ]
    [[ "$output" == *"Filebeat queue flush timeout set to 2s"* ]]
    [[ "${lines[${#lines[@]}-1]}" == "started" ]]
    [ "$(cat "$YQ_ARGS")" = "$(printf '%s\n' -i '.queue.mem.flush.timeout = "2s"' /usr/share/filebeat-logs/filebeat-logs.yml)" ]
}

@test "flush-timeout: a failed patch warns and still runs the entrypoint" {
    stub_yq 1
    run env PATH="${STUBS}:/usr/bin:/bin" bash "$SCRIPT" echo started
    [ "$status" -eq 0 ]
    [[ "$output" == *"couldn't set Filebeat's queue flush timeout"* ]]
    [[ "${lines[${#lines[@]}-1]}" == "started" ]]
}

@test "flush-timeout: no yq at all warns and still runs the entrypoint" {
    run env PATH="${STUBS}:/usr/bin:/bin" bash "$SCRIPT" echo started
    [ "$status" -eq 0 ]
    [[ "$output" == *"couldn't set Filebeat's queue flush timeout"* ]]
    [[ "${lines[${#lines[@]}-1]}" == "started" ]]
}

@test "flush-timeout: the entrypoint's exit status is Filebeat's" {
    stub_yq 0
    run env PATH="${STUBS}:/usr/bin:/bin" bash "$SCRIPT" sh -c 'exit 7'
    [ "$status" -eq 7 ]
}
