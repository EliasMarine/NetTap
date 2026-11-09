#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/remote/live-bandwidth-cleanup.sh (NET-205 rollback)
# ==========================================================================
# sudo is faked: it answers the container inspects and runs the python snippet here, on this
# machine, where fake ip and tc commands stand in for the device. tc records every call.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/remote/live-bandwidth-cleanup.sh"
NETTAP="4e4554544150424d"

load 'helpers/setup'

_stub_commands() {
    mkdir -p "$TEST_TMPDIR/bin"
    export CALLS="$TEST_TMPDIR/calls" MOCK_RUNNING="${MOCK_RUNNING:-true}" MOCK_DEL_FAIL="${MOCK_DEL_FAIL:-}"
    : > "$CALLS"
    cat > "$TEST_TMPDIR/bin/sudo" <<'STUB'
#!/usr/bin/env bash
echo "sudo $*" >> "$CALLS"
case "$*" in
    "docker inspect -f {{.State.Running}} nettap-storage-daemon") echo "$MOCK_RUNNING" ;;
    "docker inspect -f {{.Config.Image}} nettap-storage-daemon") echo "nettap/storage-daemon:test" ;;
    "docker exec nettap-storage-daemon python3 "*) shift 4; exec python3 "$@" ;;
    "docker run --rm --network host --cap-add NET_ADMIN --entrypoint python3 "*) shift 10; exec python3 "$@" ;;
    *) exit 1 ;;
esac
STUB
    cat > "$TEST_TMPDIR/bin/ip" <<'STUB'
#!/usr/bin/env bash
echo '[{"ifindex":1,"ifname":"lo"},{"ifindex":2,"ifname":"enp4s0"},{"ifindex":3,"ifname":"br0"}]'
STUB
    # enp4s0: two NetTap filters, a foreign one with a cookie, a foreign one without, and a
    # pref head line; br0: one NetTap filter; lo: nothing
    cat > "$TEST_TMPDIR/bin/tc" <<STUB
#!/usr/bin/env bash
echo "tc \$*" >> "\$CALLS"
case "\$*" in
    "-s -j filter show dev enp4s0 ingress") cat <<'JSON'
[{"protocol":"all","pref":49152,"kind":"flower","chain":0},
 {"protocol":"all","pref":49152,"kind":"flower","chain":0,"options":{"handle":1,
  "actions":[{"kind":"gact","cookie":"${NETTAP}0000000000000001"}]}},
 {"protocol":"802.1Q","pref":49156,"kind":"flower","chain":0,"options":{"handle":3,
  "actions":[{"kind":"gact","cookie":"${NETTAP}0200000000000004"}]}},
 {"protocol":"ip","pref":1,"kind":"flower","chain":0,"options":{"handle":1,
  "actions":[{"kind":"gact","cookie":"deadbeef"}]}},
 {"protocol":"ip","pref":2,"kind":"u32","chain":0,"options":{"handle":"800::800",
  "actions":[{"kind":"mirred"}]}}]
JSON
    ;;
    "-s -j filter show dev br0 ingress") echo '[{"protocol":"ip","pref":49154,"kind":"flower","options":{"handle":2,"actions":[{"cookie":"${NETTAP}0100000000000002"}]}}]' ;;
    "-s -j filter show dev lo ingress") ;;
    "filter del dev br0 "*) if [ -n "\$MOCK_DEL_FAIL" ]; then echo "RTNETLINK answers: No such file" >&2; exit 2; fi ;;
    "filter del "*) ;;
    *) exit 1 ;;
esac
STUB
    chmod +x "$TEST_TMPDIR/bin/"*
    export PATH="$TEST_TMPDIR/bin:$PATH"
}

_deletes() { grep "^tc filter del" "$CALLS" || true; }

@test "live-bandwidth-cleanup: --check lists and counts NetTap filters and deletes nothing" {
    _stub_commands
    run bash "$SCRIPT" --check
    [ "$status" -eq 1 ]
    [[ "$output" == *"nettap-storage-daemon is running"* ]]
    [[ "$output" == *"enp4s0 pref 49152 protocol all handle 1 flower"* ]]
    [[ "$output" == *"enp4s0 pref 49156 protocol 802.1Q handle 3 flower"* ]]
    [[ "$output" == *"br0 pref 49154 protocol ip handle 2 flower"* ]]
    [[ "$output" == *"3 NetTap filter(s) found"* ]]
    [[ "$output" != *"pref 1 "* && "$output" != *"pref 2 "* ]]
    [ -z "$(_deletes)" ]
}

@test "live-bandwidth-cleanup: deletes only cookie matches, by exact pref, protocol and handle" {
    _stub_commands
    run bash "$SCRIPT"
    [ "$status" -eq 0 ]
    [ "$(_deletes)" = "tc filter del dev br0 ingress pref 49154 protocol ip handle 2 flower
tc filter del dev enp4s0 ingress pref 49152 protocol all handle 1 flower
tc filter del dev enp4s0 ingress pref 49156 protocol 802.1Q handle 3 flower" ]
    [[ "$output" == *"3 of 3 NetTap filter(s) deleted"* ]]
}

@test "live-bandwidth-cleanup: never touches a qdisc, so clsact stays" {
    _stub_commands
    run bash "$SCRIPT"
    run bash "$SCRIPT" --check
    ! grep -q "qdisc" "$CALLS"
}

@test "live-bandwidth-cleanup: a failed delete exits 1 and the rest still go" {
    export MOCK_DEL_FAIL=1
    _stub_commands
    run bash "$SCRIPT"
    [ "$status" -eq 1 ]
    [[ "$output" == *"could not delete br0 pref 49154"* ]]
    [ "$(_deletes | wc -l | tr -d ' ')" -eq 3 ]
    [[ "$output" == *"2 of 3 NetTap filter(s) deleted"* ]]
}

@test "live-bandwidth-cleanup: daemon down → a throwaway container from the daemon's image" {
    export MOCK_RUNNING=false
    _stub_commands
    run bash "$SCRIPT" --check
    [[ "$output" == *"using a throwaway container from nettap/storage-daemon:test"* ]]
    grep -q "^sudo docker run --rm --network host --cap-add NET_ADMIN --entrypoint python3 nettap/storage-daemon:test -I -c" "$CALLS"
    [[ "$output" == *"3 NetTap filter(s) found"* ]]
}

@test "live-bandwidth-cleanup: works piped into bash, as from git history" {
    _stub_commands
    run bash -c "bash -s -- --check < '$SCRIPT'"
    [ "$status" -eq 1 ]
    [[ "$output" == *"3 NetTap filter(s) found"* ]]
}

@test "live-bandwidth-cleanup: bad usage exits 2 without touching docker" {
    _stub_commands
    run bash "$SCRIPT" --bogus
    [ "$status" -eq 2 ]
    [ ! -s "$CALLS" ]
}
