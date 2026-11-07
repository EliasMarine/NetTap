# shellcheck shell=bash
# Hold Suricata's rules lock from the host (NET-191 slice 2). Sourced by device scripts.
#
# The lock is /run/nettap-rules/rules.lock on the nettap-rules-state volume. nettap-rules-update.sh
# (startup, nightly and manual rule updates) and the daemon take it before they change, reload or
# restart Suricata's rules. The host can't take it directly: the volume is root's and sudo here
# allows only docker (no flock, no SETENV). So a throwaway container of the live image (it has
# flock) takes it and sleeps; removing that container releases it.
#
#   rules_lock_take <live-container>   0 held, 1 not obtained in 15 minutes, 2 no lock on this device
#                                      (suricata-live has no rules-state volume: before slice 2)
#   rules_lock_release                 safe to call when nothing is held
#
# The holder gives up by itself after RULES_LOCK_MAX_S, so a script that dies can't keep it.

RULES_LOCK_HOLDER=""
RULES_LOCK_MAX_S=1800

rules_lock_take() {
    local live="$1" volume image env uid gid
    volume=$(sudo docker inspect -f '{{range .Mounts}}{{if eq .Destination "/run/nettap-rules"}}{{.Name}}{{end}}{{end}}' "$live" 2>/dev/null)
    [ -n "$volume" ] || return 2
    image=$(sudo docker inspect -f '{{.Config.Image}}' "$live") || return 1
    env=$(sudo docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$live")
    uid=$(printf '%s\n' "$env" | sed -n 's/^PUID=//p')
    gid=$(printf '%s\n' "$env" | sed -n 's/^PGID=//p')
    RULES_LOCK_HOLDER="nettap-rules-lock-$$"
    sudo docker rm -f "$RULES_LOCK_HOLDER" >/dev/null 2>&1
    if ! sudo docker run -d --rm --name "$RULES_LOCK_HOLDER" --network none --memory 32m \
        --user "${uid:-1000}:${gid:-1000}" --cap-drop ALL --security-opt no-new-privileges \
        -v "$volume:/run/nettap-rules" --entrypoint flock "$image" \
        -w 900 /run/nettap-rules/rules.lock sh -c "echo locked; exec sleep $RULES_LOCK_MAX_S" >/dev/null; then
        RULES_LOCK_HOLDER=""
        return 1
    fi
    local _
    for _ in $(seq 1 182); do  # flock waits up to 900 s; the holder exits if it gives up
        if sudo docker logs "$RULES_LOCK_HOLDER" 2>/dev/null | grep -q '^locked$'; then
            return 0
        fi
        sudo docker inspect "$RULES_LOCK_HOLDER" >/dev/null 2>&1 || break
        sleep 5
    done
    rules_lock_release
    return 1
}

rules_lock_release() {
    [ -n "$RULES_LOCK_HOLDER" ] || return 0
    sudo docker rm -f "$RULES_LOCK_HOLDER" >/dev/null 2>&1
    RULES_LOCK_HOLDER=""
}
