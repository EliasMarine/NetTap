#!/bin/sh
# Move the daemon's alert suppressions, baselines and threat-intel cache from its /tmp tmpfs to
# the persistent data volume (release audit F4). POSIX sh, so it runs in the daemon container:
#   sudo docker exec nettap-storage-daemon sh -c "$(cat scripts/remote/migrate-daemon-state.sh)" \
#       migrate /tmp /opt/nettap/data
# deploy-release-audit.sh runs it BEFORE recreating the daemon (the tmpfs dies with the
# container). Tested in tests/scripts/test_migrate_daemon_state.bats.
#
# The live source is authoritative: until the recreate only the old daemon writes state, and it
# writes the source. So every run recopies every file, and a destination left by an earlier
# (aborted or rolled-back) run is moved aside to <name>.pre-migration-<UTC stamp>, never deleted.
# Exit 0 when every present file is in place, 1 at the first failure (the rest are untouched).
set -u

SRC="${1:?usage: migrate-daemon-state.sh SOURCE_DIR DEST_DIR}"
DST="${2:?usage: migrate-daemon-state.sh SOURCE_DIR DEST_DIR}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

for name in nettap-suppress.json nettap-baselines.json nettap-threat-intel.json; do
    if [ ! -f "$SRC/$name" ]; then
        echo "   - $name: not in $SRC, nothing to move"
        continue
    fi
    # Only the daemon's own file: a regular file, not a link, owned by the user running this
    # (root in the container). /tmp is writable by all, e.g. by dnsmasq in DHCP gateway mode.
    if [ -L "$SRC/$name" ] || [ -z "$(find "$SRC" -maxdepth 1 -name "$name" -type f -user "$(id -u)")" ]; then
        echo "   ✗ $name: not a regular file owned by $(id -un), so nothing was moved"
        exit 1
    fi
    staged="$DST/.$name.migrating"
    if ! cp "$SRC/$name" "$staged"; then
        echo "   ✗ $name: could not copy it to $staged"
        rm -f "$staged"
        exit 1
    fi
    if ! python3 -c 'import json, sys; json.load(open(sys.argv[1]))' "$staged"; then
        echo "   ✗ $name: the copy is not valid JSON, so $DST/$name was left as it was"
        rm -f "$staged"
        exit 1
    fi
    if [ -e "$DST/$name" ]; then
        if cmp -s "$staged" "$DST/$name"; then
            rm -f "$staged"
            echo "   ✓ $name: already in $DST"
            continue
        fi
        if ! mv "$DST/$name" "$DST/$name.pre-migration-$STAMP"; then
            echo "   ✗ $name: could not move the older $DST/$name aside"
            rm -f "$staged"
            exit 1
        fi
        echo "   ✓ $name: the older copy in $DST was kept as $name.pre-migration-$STAMP"
    fi
    # same filesystem, so the rename is atomic
    if ! mv "$staged" "$DST/$name"; then
        echo "   ✗ $name: could not move $staged into place"
        exit 1
    fi
    echo "   ✓ $name: moved to $DST"
done
exit 0
