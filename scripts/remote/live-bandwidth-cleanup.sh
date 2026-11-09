#!/usr/bin/env bash
# Remove every live bandwidth counter (NET-205) NetTap left on the device's interfaces.
#
# Lists `tc -s -j filter show dev <iface> ingress` on every interface and deletes only filters whose
# action cookie starts with 4e4554544150424d ("NETTAPBM"), each by its exact pref, protocol and
# handle. The clsact qdisc is never deleted: an empty one costs nothing measurable.
#
# Self-contained on purpose (bash and a stdlib-only python snippet, no daemon code), so it still
# works after the feature is reverted. It runs in the daemon container when that is up, else in a
# throwaway container from the daemon image (host network, NET_ADMIN).
#
# Run as the normal user (NOT with sudo):
#   bash scripts/remote/live-bandwidth-cleanup.sh            # delete them
#   bash scripts/remote/live-bandwidth-cleanup.sh --check    # list and count, delete nothing
# From git history, after a revert:
#   git show <sha>:scripts/remote/live-bandwidth-cleanup.sh | bash -s -- --check
#
# Exit 0 when no NetTap filter is left (--check: none found), 1 otherwise, 2 on bad usage.
set -u

CONTAINER="nettap-storage-daemon"
DEFAULT_IMAGE="nettap/storage-daemon:latest"  # docker/docker-compose.yml

# The python snippet: argv[1] is "check" or "delete".
read -r -d '' PAYLOAD <<'PY'
import json, subprocess, sys

PREFIX = "4e4554544150424d"  # "NETTAPBM": only NetTap's own filters carry it
check = sys.argv[1] == "check"


def run(*argv):
    done = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    if done.returncode:
        raise RuntimeError(done.stderr.strip() or f"exit {done.returncode}")
    return done.stdout


def ours(item):
    options = item.get("options") if isinstance(item, dict) else None
    if not isinstance(options, dict) or "handle" not in options:
        return False
    actions = [a for a in options.get("actions") or [] if isinstance(a, dict)]
    return any(str(a.get("cookie", "")).lower().startswith(PREFIX) for a in actions)


try:
    links = json.loads(run("ip", "-j", "link", "show") or "[]")
except (RuntimeError, ValueError, OSError) as exc:
    print(f"   ✗ could not list the interfaces: {exc}")
    sys.exit(1)
found = deleted = failed = 0
for iface in sorted({link["ifname"] for link in links if link.get("ifname")}):
    try:
        dump = json.loads(run("tc", "-s", "-j", "filter", "show", "dev", iface, "ingress") or "[]")
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"   ✗ {iface}: could not list the filters: {exc}")
        failed += 1
        continue
    for item in filter(ours, dump):
        found += 1
        pref, proto = str(item["pref"]), str(item["protocol"])
        handle, kind = str(item["options"]["handle"]), str(item.get("kind") or "flower")
        what = f"{iface} pref {pref} protocol {proto} handle {handle} {kind}"
        if check:
            print(f"   • {what}")
            continue
        try:
            run("tc", "filter", "del", "dev", iface, "ingress",
                "pref", pref, "protocol", proto, "handle", handle, kind)
            print(f"   ✓ deleted {what}")
            deleted += 1
        except (RuntimeError, OSError) as exc:
            print(f"   ✗ could not delete {what}: {exc}")
            failed += 1
if check:
    print(f"   {found} NetTap filter(s) found")
else:
    print(f"   {deleted} of {found} NetTap filter(s) deleted")
sys.exit(1 if failed or (check and found) else 0)
PY

main() {
    local mode="delete" verb="List and delete" image status
    local -a runner
    case "${1:-}" in
        "") ;;
        --check) mode="check"; verb="List" ;;
        *) echo "Usage: bash scripts/remote/live-bandwidth-cleanup.sh [--check]"; exit 2 ;;
    esac

    echo "=== Live bandwidth counters: ${mode} ==="
    echo ""
    echo "→ Step 1: Find a container with tc..."
    # no -i on docker: when this script is piped into bash, stdin is the script itself
    if [ "$(sudo docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ]; then
        echo "   ✓ $CONTAINER is running"
        runner=(sudo docker exec "$CONTAINER" python3)
    else
        image=$(sudo docker inspect -f '{{.Config.Image}}' "$CONTAINER" 2>/dev/null)
        image="${image:-$DEFAULT_IMAGE}"
        echo "   ✓ $CONTAINER isn't running: using a throwaway container from $image"
        # root in the container: the image runs as nettap, and Docker grants added capabilities
        # only to root, so every delete failed with EPERM (sec review LOW-2)
        # OLD CODE: runner=(sudo docker run --rm --network host --cap-add NET_ADMIN --entrypoint python3 "$image")
        runner=(sudo docker run --rm --user 0 --network host --cap-drop ALL --cap-add NET_ADMIN --security-opt no-new-privileges --entrypoint python3 "$image")
    fi
    echo ""

    echo "→ Step 2: $verb NetTap filters on every interface..."
    "${runner[@]}" -I -c "$PAYLOAD" "$mode"
    status=$?
    echo ""
    if [ "$status" -eq 0 ]; then
        echo "=== Done: no NetTap filter is left ==="
    elif [ "$mode" = "check" ]; then
        echo "=== NetTap filters remain (or an interface couldn't be read): run without --check ==="
    else
        echo "=== Some filters couldn't be removed (✗ above) ==="
    fi
    exit "$status"
}

main "$@"
