#!/usr/bin/env bash
# Roll the web UI back to the commit that was deployed before the redesign.
#
# deploy-ui-redesign.sh records that commit in /home/nettap/.nettap-last-deploy.
# This checks it out (detached, no pull), rebuilds and recreates only nettap-web,
# and runs the deploy script's health checks. Pass a commit to use that instead.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/rollback-ui-redesign.sh
#   bash /home/nettap/NetTap/scripts/remote/rollback-ui-redesign.sh <commit>
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
LAST_DEPLOY_FILE="${LAST_DEPLOY_FILE:-/home/nettap/.nettap-last-deploy}"

echo "→ Find the commit to roll back to..."
if [ $# -ge 1 ]; then
    SHA="$1"
    echo "   using the commit given: $SHA"
elif [ -s "$LAST_DEPLOY_FILE" ]; then
    SHA=$(tr -d '[:space:]' < "$LAST_DEPLOY_FILE")
    echo "   using the commit recorded in $LAST_DEPLOY_FILE: $SHA"
else
    echo "   ✗ No commit given and $LAST_DEPLOY_FILE is missing or empty."
    echo "     Find the commit with: git -C $REPO_DIR log --oneline -10 origin/main"
    echo "     Then run: bash $REPO_DIR/scripts/remote/rollback-ui-redesign.sh <commit>"
    exit 1
fi

cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
git fetch origin || echo "   (fetch failed; using the commits already on the device)"
# Resolve before handing over, so a typo stops here and nothing is rebuilt
if ! FULL=$(git rev-parse --verify --quiet "${SHA}^{commit}"); then
    echo "   ✗ $SHA is not a commit in $REPO_DIR — nothing was changed"
    exit 1
fi
echo "   ✓ $(git log -1 --format='%h %s' "$FULL")"
echo ""

# Run a copy: checking out the old commit rewrites the deploy script on disk, and bash
# reads a script as it runs, so the original would change under it
DEPLOY_COPY=$(mktemp)
trap 'rm -f "$DEPLOY_COPY"' EXIT
cp "$REPO_DIR/scripts/remote/deploy-ui-redesign.sh" "$DEPLOY_COPY"
TARGET_SHA="$FULL" bash "$DEPLOY_COPY"
