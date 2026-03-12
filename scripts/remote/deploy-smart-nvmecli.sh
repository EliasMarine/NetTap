#!/usr/bin/env bash
# Deploy nvme-cli SMART monitoring upgrade and verify it works.
# Run on the NetTap device: sudo bash scripts/remote/deploy-smart-nvmecli.sh

set -u

REPO_DIR="$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)/NetTap"
COMPOSE="docker compose -f $REPO_DIR/docker/docker-compose.yml"

echo "=== NetTap: Deploy nvme-cli SMART Monitoring ==="
echo "Date: $(date)"
echo ""

# --- Step 1: Pull latest code ---
echo "→ Step 1: Pulling latest code..."
cd "$REPO_DIR" || { echo "FAIL: $REPO_DIR not found"; exit 1; }
git pull origin phase-5/mirror-span-mode || { echo "FAIL: git pull failed"; exit 1; }
echo "  OK"
echo ""

# --- Step 2: Rebuild daemon container (picks up nvme-cli package + SYS_ADMIN cap) ---
echo "→ Step 2: Rebuilding nettap-storage-daemon image..."
sudo $COMPOSE build nettap-storage-daemon || { echo "FAIL: build failed"; exit 1; }
echo "  OK"
echo ""

# --- Step 3: Recreate daemon container ---
echo "→ Step 3: Recreating daemon container..."
sudo $COMPOSE up -d nettap-storage-daemon --force-recreate || { echo "FAIL: up failed"; exit 1; }
echo "  OK"
echo ""

# --- Step 4: Wait for daemon to be healthy ---
echo "→ Step 4: Waiting for daemon health check (up to 60s)..."
for i in $(seq 1 12); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    echo "  Attempt $i/12: $STATUS"
    if [ "$STATUS" = "healthy" ]; then
        break
    fi
    sleep 5
done

FINAL_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
if [ "$FINAL_STATUS" != "healthy" ]; then
    echo "  WARNING: Daemon not healthy after 60s (status: $FINAL_STATUS)"
    echo "  Continuing with tests anyway..."
fi
echo ""

# --- Step 5: Verify nvme-cli is installed in the container ---
echo "→ Step 5: Checking nvme-cli installed in container..."
sudo docker exec nettap-storage-daemon nvme version 2>&1 || echo "  WARNING: nvme-cli not found in container"
echo ""

# --- Step 6: Verify SYS_ADMIN capability ---
echo "→ Step 6: Checking container capabilities..."
sudo docker inspect --format='{{.HostConfig.CapAdd}}' nettap-storage-daemon
echo ""

# --- Step 7: Test nvme-cli directly inside the container ---
echo "→ Step 7: Testing nvme smart-log directly..."
NVME_DEV=$(sudo docker exec nettap-storage-daemon sh -c 'ls /dev/nvme[0-9] 2>/dev/null | head -1')
if [ -n "$NVME_DEV" ]; then
    echo "  Found NVMe controller: $NVME_DEV"
    echo "  --- nvme smart-log output ---"
    sudo docker exec nettap-storage-daemon nvme smart-log "$NVME_DEV" -o json 2>&1 | head -30
    echo ""
    echo "  --- nvme id-ctrl output (model/serial) ---"
    sudo docker exec nettap-storage-daemon nvme id-ctrl "$NVME_DEV" -o json 2>&1 | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f\"  Model:  {d.get('mn', 'N/A').strip()}\")
    print(f\"  Serial: {d.get('sn', 'N/A').strip()}\")
    print(f\"  FW:     {d.get('fr', 'N/A').strip()}\")
except Exception as e:
    print(f'  Parse error: {e}')
"
else
    echo "  No NVMe controller found at /dev/nvme*"
    echo "  Checking namespace devices..."
    sudo docker exec nettap-storage-daemon ls -la /dev/nvme* 2>&1 || echo "  No NVMe devices at all"
fi
echo ""

# --- Step 8: Test SMART health API endpoint ---
echo "→ Step 8: Testing SMART health API..."
SMART_RESP=$(sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/smart/health 2>&1)
echo "$SMART_RESP" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f\"  Device:      {d.get('device', 'N/A')}\")
    print(f\"  Type:        {d.get('device_type', 'N/A')}\")
    print(f\"  Model:       {d.get('model', 'N/A')}\")
    print(f\"  Serial:      {d.get('serial', 'N/A')}\")
    print(f\"  Temperature: {d.get('temperature_c', 'N/A')}°C\")
    print(f\"  Wear:        {d.get('percentage_used', 'N/A')}%\")
    print(f\"  Power Hours: {d.get('power_on_hours', 'N/A')}\")
    print(f\"  Healthy:     {d.get('healthy', 'N/A')}\")
    tbw = d.get('total_bytes_written')
    if tbw is not None:
        print(f\"  TBW:         {tbw / (1024**4):.2f} TB\")
    else:
        print(f\"  TBW:         N/A\")
    warnings = d.get('warnings', [])
    if warnings:
        print(f\"  Warnings:    {warnings}\")
except Exception as e:
    print(f'  Raw response: {sys.stdin.read()[:500]}')
    print(f'  Parse error: {e}')
" 2>&1
echo ""

# --- Step 9: Test SMART diagnostics endpoint ---
echo "→ Step 9: Testing SMART diagnostics API..."
DIAG_RESP=$(sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/smart/diagnostics 2>&1)
echo "$DIAG_RESP" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f\"  Raw data available: {d.get('raw_output_available', 'N/A')}\")
    print(f\"  Missing fields:    {d.get('missing_fields', 'N/A')}\")
    guidance = d.get('guidance', [])
    if guidance:
        for g in guidance:
            print(f\"  Guidance: {g}\")
    else:
        print(f\"  Guidance:          None (all fields present)\")
except Exception as e:
    print(f'  Parse error: {e}')
" 2>&1
echo ""

# --- Step 10: Check daemon logs for SMART activity ---
echo "→ Step 10: Daemon SMART-related logs (last 30 lines)..."
sudo docker logs nettap-storage-daemon --tail 100 2>&1 | grep -iE "smart|nvme|temperature|wear|health|monitor" | tail -30
echo ""

# --- Summary ---
echo "=== Deploy Complete ==="
echo ""
echo "Key things to check:"
echo "  1. Temperature should be a number (not null) — means nvme-cli is working"
echo "  2. Model/Serial should show your actual drive name"
echo "  3. Missing fields should be empty [] — all data present"
echo "  4. If temperature is null, check Step 7 output for nvme-cli errors"
echo ""
echo "Paste the FULL output above back to Claude for analysis."
