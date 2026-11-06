# 2026-11-06 — Device checks treat PCAP switched off in Settings as a setting, not a fault (NET-179)

**Status:** branch `fix/device-checks-pcap-off`.

**Problem**
- On the G11 (2026-11-06), the accuracy audit reported two failures:
  - ✗ "every NetTap container up and healthy" (`nettap-pcap-capture Exited (0)`);
  - ✗ "netsniff is writing PCAP" (newest file 75,726 s old).
- `fix-pcap-capture-stopped.sh` found the cause: PCAP capture is switched off in Settings.
  - `/opt/nettap/data/.env` holds `PCAP_CAPTURE_ENABLED="false"`. It was written at 00:32:59 UTC, 1.8 s before the container stopped (exit 0).
  - nginx logged `PUT /api/capture/toggle` from the Settings page at 00:33:01. The same pattern happened on 4 Nov at 17:24:30.
  - So nothing failed: someone clicked the PCAP collection switch.
- `deploy-decimal-units.sh` ended by saying the disk "matches the drive's label (1 TB, not 931 GB)". The G11's drive is 1.97 TB.

**Fix**
- `scripts/remote/verify-acceptance.sh` reads the setting from the daemon's `.env`.
  - When capture is off, it prints that, leaves the stopped capture container out of the health check, and prints the PCAP age as information instead of a ✗.
  - When capture is on, both checks are unchanged.
- `scripts/remote/deploy-decimal-units.sh`'s closing line no longer names a drive size.

**Tests**
- Ran on the G11 over SSH:
  - The `.env` pattern matches the real file.
  - The container filter drops `nettap-pcap-capture Exited (0) 22 hours ago` with capture off and keeps it with capture on.
- shellcheck and `bash -n` are clean.

**Open:** whether PCAP should be on. That's the owner's call; nothing was switched on.
