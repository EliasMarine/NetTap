# The deploy figure checks follow the pages again (NET-194)

## Problem

Two read-only checks that deploy scripts run failed on `main` while the pages were right. Their ✗ lines were expected, so a real regression could hide among them.

- `scripts/remote/verify-figures.sh`, "alert total" and "high-severity alerts". The raw query counted every Suricata alert. Since #197 (NET-191 slice 1), `/api/alerts/count` leaves out the alerts ET rates Informational or Unknown and lists them as activity. On the G11 that meant 17 counted against 2,645 raw.
- `scripts/remote/verify_device_figures.py`:
  - **Top destinations:** the check expected them in connection order. NET-158 sorts them by bytes. Result: 67 "not sorted by connections" and "left out" lines across 52 devices.
  - **Alert counts:** found once the first problem was fixed. PR #174 made Devices and Device detail count the alerts on a device's traffic both ways (sender or receiver). The check still counted only the alerts the device sent, so .44, .205 and .24 showed 51, 41 and 223 against 0.

## Root cause

Each page change was deliberate, but the deploy-time check for that figure wasn't updated in the same PR.

## Fix

- `verify-figures.sh`:
  - The raw alert query now leaves out `suricata.alert.metadata.signature_severity` Informational and Unknown. The rule is written out rather than imported, so the check tests the rule instead of repeating it.
  - New line, "activity alerts": `/api/alerts/count?activity=true` is compared with a raw count of those alerts.
- `verify_device_figures.py`:
  - Device detail's top destinations are checked by bytes against a raw per-destination sum, as the device-by-MAC check already did. Each listed destination's connection count is still bracketed.
  - Device detail and the Devices list count alerts both ways. The Devices list adds the sender and receiver counts, as the daemon does.
  - Risk keeps the sent-only count, because `api/risk.py` scores the alerts a device raised.
- The old lines are kept as OLD CODE.

## Files

- scripts/remote/verify-figures.sh
- scripts/remote/verify_device_figures.py

## Tests

- `daemon/tests/test_verify_device_figures.py`: 5 passed; the pure helpers didn't change.
- shellcheck and ruff check are clean.
- G11, 2026-11-07, read-only, run from the branch:
  - `verify-figures.sh`: "Every page figure matches OpenSearch". Alert total 18 = 18, activity 2,428 = 2,428.
  - `verify-device-figures.sh`: RESULT 0 across 53 devices and 53 MACs.

## Lessons

- When a PR deliberately changes a figure, update the deploy-time check that compares it with OpenSearch in the same PR.
- A check with known ✗ lines hides new ones. The alert-count mismatch here only showed up after the 67 destination lines were gone.
