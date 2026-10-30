#!/usr/bin/env bash
# Deploy pcap-capture SETFCAP fix and verify PCAP writing
set -euo pipefail

cd ~/NetTap

echo "=== Pulling latest ==="
git pull origin phase-4/webui-v2

echo "=== Recreating pcap-capture ==="
sudo docker compose -f docker/docker-compose.yml up -d pcap-capture --force-recreate

echo "=== Waiting 15s for supervisord to start netsniff-ng ==="
sleep 15

echo "=== supervisord status ==="
sudo docker exec nettap-pcap-capture supervisorctl status 2>&1

echo ""
echo "=== netsniff-ng file caps (should be empty after setcap -r) ==="
sudo docker exec nettap-pcap-capture getcap /usr/sbin/netsniff-ng 2>&1

echo ""
echo "=== netsniff-ng stderr log ==="
sudo docker exec nettap-pcap-capture bash -c 'cat /tmp/netsniff-br0-stderr---supervisor-*.log 2>/dev/null | tail -10' || echo "No stderr log"

echo ""
echo "=== waiting 30s for PCAP files to appear ==="
sleep 30

echo "=== /pcap directory ==="
sudo docker exec nettap-pcap-capture ls -lah /pcap/ 2>&1

echo ""
echo "=== container status ==="
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep pcap
