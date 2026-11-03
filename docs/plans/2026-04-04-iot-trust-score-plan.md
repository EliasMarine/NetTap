# IoT Trust Score Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the basic IoT page with an IoT Trust Score dashboard that gives home users a "credit score for your smart home" — combining security scoring, privacy monitoring, and behavioral change detection.

**Architecture:** Backend adds 7 new endpoints to the existing aiohttp daemon, extending the IoTMonitor service and adding new service classes. Two static data files (tracker domains, protocol profiles) power the privacy and protocol audit features. Frontend replaces the existing `/iot/+page.svelte` with a new page using existing components (HorizontalBarList, DetailDrawer, TimeSeriesChart, DonutChart). The catch-all proxy at `web/src/routes/api/[...path]/+server.ts` handles all `/api/iot/*` routing.

**Tech Stack:** Python/aiohttp (backend), Svelte 5 with runes (frontend), OpenSearch query DSL, pure SVG charts

**Design doc:** `docs/plans/2026-04-04-iot-trust-score-design.md`

---

## Phase 1: Data Files & Scoring Service

### Task 1: Create Tracker Domains List

**Files:**
- Create: `daemon/data/tracker_domains.txt`

**Step 1: Create the tracker domains file**

```txt
# Known analytics, tracking, and telemetry domains
# Used by the IoT privacy report to score device privacy behavior.
# One domain per line. Lines starting with # are comments.

# --- Analytics platforms ---
crashlytics.com
firebase-settings.crashlytics.com
app-measurement.com
analytics.google.com
google-analytics.com
googletagmanager.com
mixpanel.com
amplitude.com
segment.io
segment.com
heapanalytics.com
fullstory.com
hotjar.com
mouseflow.com
luckyorange.com
clarity.ms
newrelic.com
nr-data.net
bugsnag.com
sentry.io

# --- Ad networks ---
doubleclick.net
googlesyndication.com
googleadservices.com
facebook.com
graph.facebook.com
ads.facebook.com
pixel.facebook.com
advertising.apple.com
adsserver.org

# --- IoT-specific telemetry ---
data.flurry.com
metrics.icloud.com
xp.apple.com
settings.crashlytics.com
device-metrics-us.amazon.com
device-metrics-us-2.amazon.com
unagi.amazon.com
fls-na.amazon.com
mads.amazon.com
aax.amazon.com
us.tplinkcloud.com
n-devs.tplinkcloud.com
ewelink-api.coolkit.cc
tuya.com
a.]]tuya.com
smartlife-app-service.tuyaus.com
smart.tuya.com
ozu4e1rjhg.execute-api.us-east-1.amazonaws.com
dcape.roku.com
logs.roku.com
cooper.roku.com
p.]typekit.net
samsungcloudsolution.com
samsungacr.com
gpm.samsungqbe.com
config.samsungads.com
cdn.samsungcloudsolution.com
osb-apps.samsungqbe.com
acr0.samsungcloudsolution.com
log-config.samsungacr.com
vizio.com
tvinteractive.tv
scribe.logs.roku.com
ingest.sentry.io

# --- Data brokers / tracking ---
scorecardresearch.com
quantserve.com
adsrvr.org
taboola.com
outbrain.com
criteo.com
pubmatic.com
rubiconproject.com
openx.net
casalemedia.com
adnxs.com
moatads.com
doubleverify.com

# --- Telemetry CDNs ---
sb.scorecardresearch.com
b.scorecardresearch.com
udp.scorecardresearch.com
```

**Step 2: Commit**

```bash
git add daemon/data/tracker_domains.txt
git commit -m "feat(iot): add tracker domains list for privacy scoring"
```

---

### Task 2: Create Protocol Profiles

**Files:**
- Create: `daemon/data/protocol_profiles.json`

**Step 1: Create the protocol profiles file**

```json
{
  "_comment": "Expected port/protocol sets per IoT device category. Ports not in this list are flagged as unexpected by the protocol audit.",
  "camera": {
    "label": "Security Camera",
    "expected_ports": [80, 443, 554, 8554, 8080, 8443, 53, 123],
    "expected_protocols": ["tcp", "udp"],
    "notes": "554/8554 = RTSP, 123 = NTP"
  },
  "smart_speaker": {
    "label": "Smart Speaker",
    "expected_ports": [443, 8443, 53, 123, 5353, 1900],
    "expected_protocols": ["tcp", "udp"],
    "notes": "5353 = mDNS, 1900 = SSDP/UPnP"
  },
  "thermostat": {
    "label": "Thermostat",
    "expected_ports": [443, 8883, 1883, 53, 123],
    "expected_protocols": ["tcp", "udp"],
    "notes": "8883 = MQTT over TLS, 1883 = MQTT"
  },
  "smart_plug": {
    "label": "Smart Plug/Switch",
    "expected_ports": [443, 8883, 1883, 53, 123, 6668, 6669],
    "expected_protocols": ["tcp", "udp"],
    "notes": "6668/6669 = Tuya protocol"
  },
  "smart_tv": {
    "label": "Smart TV / Streaming",
    "expected_ports": [80, 443, 8443, 53, 123, 5353, 1900, 8008, 8009, 8443, 9080],
    "expected_protocols": ["tcp", "udp"],
    "notes": "8008/8009 = Chromecast, 1900 = DLNA"
  },
  "hub": {
    "label": "Smart Home Hub",
    "expected_ports": [80, 443, 8443, 8080, 53, 123, 5353, 1900, 8883, 1883, 25105],
    "expected_protocols": ["tcp", "udp"],
    "notes": "25105 = Insteon"
  },
  "doorbell": {
    "label": "Video Doorbell",
    "expected_ports": [443, 8443, 554, 8554, 53, 123],
    "expected_protocols": ["tcp", "udp"],
    "notes": "Same as camera + cloud only"
  },
  "light": {
    "label": "Smart Light",
    "expected_ports": [443, 80, 53, 123, 5353, 1900, 8010],
    "expected_protocols": ["tcp", "udp"],
    "notes": "8010 = Hue bridge"
  },
  "sensor": {
    "label": "Sensor / Monitor",
    "expected_ports": [443, 8883, 1883, 53, 123],
    "expected_protocols": ["tcp", "udp"],
    "notes": "Minimal — cloud + MQTT"
  },
  "default": {
    "label": "Generic IoT",
    "expected_ports": [80, 443, 53, 123, 5353, 1900],
    "expected_protocols": ["tcp", "udp"],
    "notes": "Fallback — HTTP(S), DNS, NTP, mDNS, SSDP"
  }
}
```

**Step 2: Commit**

```bash
git add daemon/data/protocol_profiles.json
git commit -m "feat(iot): add protocol profiles for IoT device categories"
```

---

### Task 3: IoT Trust Score Service

**Files:**
- Create: `daemon/services/iot_trust_scorer.py`
- Test: `daemon/tests/test_iot_trust_scorer.py`

**Step 1: Write the failing tests**

```python
"""Tests for daemon/services/iot_trust_scorer.py"""

import sys, os
from unittest.mock import MagicMock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.iot_trust_scorer import IoTTrustScorer


@pytest.fixture
def scorer():
    return IoTTrustScorer()


class TestScoreDevice:
    def test_perfect_device_gets_A(self, scorer):
        stats = {
            "tracker_domain_count": 0,
            "telemetry_bytes": 1000,
            "third_party_orgs": 1,
            "encryption_ratio": 1.0,
            "protocol_violations": 0,
            "alert_count": 0,
            "firmware_age_signal": "current",
            "baseline_adherence": 1.0,
            "new_destinations": 0,
            "volume_spike": False,
            "unusual_timing": False,
        }
        result = scorer.score_device(stats)
        assert result["score"] >= 90
        assert result["grade"] == "A"

    def test_terrible_device_gets_F(self, scorer):
        stats = {
            "tracker_domain_count": 30,
            "telemetry_bytes": 500_000_000,
            "third_party_orgs": 15,
            "encryption_ratio": 0.1,
            "protocol_violations": 5,
            "alert_count": 10,
            "firmware_age_signal": "stale",
            "baseline_adherence": 0.3,
            "new_destinations": 10,
            "volume_spike": True,
            "unusual_timing": True,
        }
        result = scorer.score_device(stats)
        assert result["score"] < 40
        assert result["grade"] == "F"

    def test_score_has_three_subscores(self, scorer):
        stats = {
            "tracker_domain_count": 5,
            "telemetry_bytes": 50_000,
            "third_party_orgs": 3,
            "encryption_ratio": 0.95,
            "protocol_violations": 0,
            "alert_count": 0,
            "firmware_age_signal": "unknown",
            "baseline_adherence": 0.9,
            "new_destinations": 1,
            "volume_spike": False,
            "unusual_timing": False,
        }
        result = scorer.score_device(stats)
        assert "privacy_score" in result
        assert "security_score" in result
        assert "behavior_score" in result
        assert 0 <= result["privacy_score"] <= 100
        assert 0 <= result["security_score"] <= 100
        assert 0 <= result["behavior_score"] <= 100


class TestGradeMapping:
    def test_grade_A(self, scorer):
        assert scorer.score_to_grade(95) == "A"
        assert scorer.score_to_grade(90) == "A"

    def test_grade_B(self, scorer):
        assert scorer.score_to_grade(80) == "B"

    def test_grade_C(self, scorer):
        assert scorer.score_to_grade(65) == "C"

    def test_grade_D(self, scorer):
        assert scorer.score_to_grade(50) == "D"

    def test_grade_F(self, scorer):
        assert scorer.score_to_grade(30) == "F"


class TestFleetScore:
    def test_fleet_score_harmonic_mean(self, scorer):
        device_scores = [95, 90, 85, 20]  # One bad device
        result = scorer.compute_fleet_score(device_scores)
        # Harmonic mean pulls down heavily toward worst device
        assert result < 70
        assert result > 0

    def test_empty_fleet(self, scorer):
        result = scorer.compute_fleet_score([])
        assert result == 100  # No devices = no problems
```

**Step 2: Run tests to verify they fail**

Run: `cd daemon && python -m pytest tests/test_iot_trust_scorer.py -v`
Expected: FAIL (module not found)

**Step 3: Write the implementation**

Create `daemon/services/iot_trust_scorer.py`:

```python
"""IoT Trust Score computation.

Computes per-device trust scores (0-100) across three pillars:
- Privacy (30 pts): tracker domains, telemetry volume, third-party sharing
- Security (40 pts): encryption ratio, protocol compliance, alerts, firmware
- Behavior (30 pts): baseline adherence, new destinations, volume spikes, timing
"""

import logging

logger = logging.getLogger("nettap.services.iot_trust_scorer")


class IoTTrustScorer:
    """Computes IoT device trust scores."""

    # --- Privacy weights (30 pts total) ---
    _PRIV_TRACKERS_MAX = 10        # 0 trackers = 10, 20+ = 0
    _PRIV_TELEMETRY_MAX = 10       # Low volume = 10, high = 0
    _PRIV_THIRD_PARTY_MAX = 10     # 1 org = 10, 10+ = 0

    # --- Security weights (40 pts total) ---
    _SEC_ENCRYPTION_MAX = 15       # 100% TLS = 15, 0% = 0
    _SEC_PROTOCOL_MAX = 10         # 0 violations = 10
    _SEC_ALERTS_MAX = 10           # 0 alerts = 10
    _SEC_FIRMWARE_MAX = 5          # Current = 5, stale = 0

    # --- Behavior weights (30 pts total) ---
    _BEH_BASELINE_MAX = 15         # 100% adherence = 15
    _BEH_NEW_DEST_MAX = 5          # 0 new = 5
    _BEH_VOLUME_MAX = 5            # No spike = 5
    _BEH_TIMING_MAX = 5            # Normal hours = 5

    def score_device(self, stats: dict) -> dict:
        """Score a single device. Returns score, grade, and sub-scores."""
        privacy = self._score_privacy(stats)
        security = self._score_security(stats)
        behavior = self._score_behavior(stats)

        total = privacy + security + behavior
        grade = self.score_to_grade(total)

        return {
            "score": total,
            "grade": grade,
            "privacy_score": round(privacy * 100 / 30),
            "security_score": round(security * 100 / 40),
            "behavior_score": round(behavior * 100 / 30),
            "privacy_raw": round(privacy, 1),
            "security_raw": round(security, 1),
            "behavior_raw": round(behavior, 1),
        }

    def _score_privacy(self, stats: dict) -> float:
        trackers = stats.get("tracker_domain_count", 0)
        telem = stats.get("telemetry_bytes", 0)
        orgs = stats.get("third_party_orgs", 1)

        t_score = max(0, self._PRIV_TRACKERS_MAX - trackers * 0.5)
        v_score = self._PRIV_TELEMETRY_MAX * max(0, 1 - telem / 100_000_000)
        o_score = max(0, self._PRIV_THIRD_PARTY_MAX - (orgs - 1) * 1.0)

        return min(30, t_score + v_score + o_score)

    def _score_security(self, stats: dict) -> float:
        enc_ratio = stats.get("encryption_ratio", 1.0)
        violations = stats.get("protocol_violations", 0)
        alerts = stats.get("alert_count", 0)
        firmware = stats.get("firmware_age_signal", "unknown")

        e_score = self._SEC_ENCRYPTION_MAX * enc_ratio
        p_score = max(0, self._SEC_PROTOCOL_MAX - violations * 3)
        a_score = max(0, self._SEC_ALERTS_MAX - alerts * 2)
        f_score = {"current": 5, "recent": 3, "unknown": 2, "stale": 0}.get(firmware, 2)

        return min(40, e_score + p_score + a_score + f_score)

    def _score_behavior(self, stats: dict) -> float:
        adherence = stats.get("baseline_adherence", 1.0)
        new_dest = stats.get("new_destinations", 0)
        spike = stats.get("volume_spike", False)
        timing = stats.get("unusual_timing", False)

        b_score = self._BEH_BASELINE_MAX * adherence
        d_score = max(0, self._BEH_NEW_DEST_MAX - new_dest)
        v_score = 0 if spike else self._BEH_VOLUME_MAX
        t_score = 0 if timing else self._BEH_TIMING_MAX

        return min(30, b_score + d_score + v_score + t_score)

    @staticmethod
    def score_to_grade(score: int) -> str:
        if score >= 90:
            return "A"
        if score >= 75:
            return "B"
        if score >= 60:
            return "C"
        if score >= 40:
            return "D"
        return "F"

    @staticmethod
    def compute_fleet_score(device_scores: list[int]) -> int:
        """Harmonic mean — one bad device tanks the fleet score."""
        if not device_scores:
            return 100
        # Avoid division by zero: treat 0-score devices as 1
        safe = [max(s, 1) for s in device_scores]
        harmonic = len(safe) / sum(1.0 / s for s in safe)
        return round(harmonic)
```

**Step 4: Run tests to verify they pass**

Run: `cd daemon && python -m pytest tests/test_iot_trust_scorer.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add daemon/services/iot_trust_scorer.py daemon/tests/test_iot_trust_scorer.py
git commit -m "feat(iot): add IoT trust score service with privacy/security/behavior pillars"
```

---

## Phase 2: Backend API Endpoints

### Task 4: Fleet Summary Endpoint

**Files:**
- Modify: `daemon/api/iot.py` (add new handler + route)
- Modify: `daemon/services/iot_monitor.py` (add `get_fleet_summary` method)
- Test: `daemon/tests/test_iot_monitor.py` (extend)

**Step 1: Write the failing test**

Add to `daemon/tests/test_iot_monitor.py`:

```python
class TestFleetSummary:
    def test_fleet_summary_returns_health_score(self, iot, mock_client):
        # Mock: 2 IoT devices classified
        iot._iot_devices = {
            "AA:BB:CC:DD:EE:FF": {"mac": "AA:BB:CC:DD:EE:FF", "manufacturer": "Ring"},
            "11:22:33:44:55:66": {"mac": "11:22:33:44:55:66", "manufacturer": "Roku"},
        }
        # Mock: baseline data exists
        iot._baselines = {
            "AA:BB:CC:DD:EE:FF": {"known_destinations": ["1.2.3.4"], "known_ports": [443], "known_countries": ["US"], "daily_avg_bytes": 1000, "connection_count": 100},
            "11:22:33:44:55:66": {"known_destinations": ["5.6.7.8"], "known_ports": [443, 80], "known_countries": ["US", "DE"], "daily_avg_bytes": 5000, "connection_count": 200},
        }
        # Mock OpenSearch returns for privacy/security queries
        mock_client.search.return_value = {"hits": {"total": {"value": 0}}, "aggregations": {}}

        result = iot.get_fleet_summary()
        assert "health_score" in result
        assert "health_grade" in result
        assert "device_count" in result
        assert "devices" in result
```

**Step 2: Run test — expect FAIL** (`get_fleet_summary` not defined)

**Step 3: Implement `get_fleet_summary()` in `daemon/services/iot_monitor.py`**

This method:
1. Gets all IoT devices
2. For each, builds stats dict (tracker count from DNS queries, encryption ratio from conn logs, anomaly count)
3. Calls IoTTrustScorer.score_device() on each
4. Computes fleet score via harmonic mean
5. Returns summary with stat card values

**Step 4: Add handler in `daemon/api/iot.py`:**

```python
async def handle_fleet_summary(request: web.Request) -> web.Response:
    """GET /api/iot/fleet-summary"""
    iot: IoTMonitor = request.app["iot_monitor"]
    from_ts, to_ts = _parse_time_range(request)
    excluded = request.app.get("excluded_ips", [])
    try:
        result = iot.get_fleet_summary(from_ts, to_ts, excluded_ips=excluded)
        return web.json_response(result)
    except Exception as exc:
        logger.error("Fleet summary failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)
```

Register in `register_iot_routes()`:
```python
app.router.add_get("/api/iot/fleet-summary", handle_fleet_summary)
```

**Step 5: Run tests — expect PASS**

**Step 6: Commit**

```bash
git commit -m "feat(iot): add fleet summary endpoint with trust scoring"
```

---

### Task 5: Privacy Report Endpoint

**Files:**
- Modify: `daemon/services/iot_monitor.py` (add `get_privacy_report`)
- Modify: `daemon/api/iot.py` (add handler + route)
- Test: `daemon/tests/test_iot_monitor.py` (extend)

**Implementation:** For each IoT device:
1. Query DNS logs for `source.mac = device_mac`, aggregate by `zeek.dns.query.keyword`
2. Match queried domains against `daemon/data/tracker_domains.txt` (loaded once on startup, suffix matching)
3. Query conn logs for `source.mac = device_mac`, bucket by: has corresponding SSL record (encrypted) vs not
4. Count distinct destination ASN orgs
5. Score privacy via IoTTrustScorer

**Endpoint:** `GET /api/iot/privacy-report?from=&to=`

**Response:**
```json
{
  "devices": [
    {
      "mac": "AA:BB:CC:DD:EE:FF",
      "name": "Ring Doorbell",
      "privacy_grade": "B",
      "privacy_score": 72,
      "tracker_domains": [{"domain": "crashlytics.com", "query_count": 45}],
      "tracker_count": 3,
      "telemetry_bytes": 12500,
      "third_party_orgs": 2,
      "encryption_ratio": 0.95,
      "phone_home_per_hour": 12.5
    }
  ]
}
```

---

### Task 6: Communication Map Endpoint

**Files:**
- Modify: `daemon/services/iot_monitor.py` (add `get_communication_map`)
- Modify: `daemon/api/iot.py` (add handler + route)

**Implementation:** For a single device (by MAC):
1. Query conn logs aggregated by `destination.ip.keyword` with sub-aggs for ports, bytes, geo, first/last seen
2. Cross-reference DNS logs to resolve IPs → hostnames
3. Compare each destination against the device's baseline (`in_baseline` flag)
4. Sort by bytes descending

**Endpoint:** `GET /api/iot/devices/{mac}/communication-map?from=&to=`

**Response:**
```json
{
  "mac": "AA:BB:CC:DD:EE:FF",
  "destinations": [
    {
      "ip": "54.239.28.85",
      "hostname": "fw.ring.com",
      "country": "US",
      "ports": [443],
      "bytes_sent": 12500,
      "bytes_received": 45000,
      "connection_count": 234,
      "first_seen": "2026-03-01T...",
      "last_seen": "2026-04-04T...",
      "in_baseline": true
    }
  ]
}
```

---

### Task 7: Activity Timeline Endpoint

**Files:**
- Modify: `daemon/services/iot_monitor.py` (add `get_activity_timeline`)
- Modify: `daemon/api/iot.py` (add handler + route)

**Implementation:** For a single device:
1. Query conn logs with `date_histogram` on `@timestamp`, interval=1h, over 7 days
2. Each bucket: connection count, sum bytes, cardinality of destinations
3. Overlay baseline active hours from `_baselines[mac]`

**Endpoint:** `GET /api/iot/devices/{mac}/activity-timeline?from=&to=`

**Response:**
```json
{
  "mac": "AA:BB:CC:DD:EE:FF",
  "interval": "1h",
  "buckets": [
    {"time": "2026-04-04T00:00:00Z", "connections": 12, "bytes": 45000, "destinations": 3}
  ],
  "baseline_hours": [8, 9, 10, 11, 12, 13, 14, 17, 18, 19, 20, 21],
  "baseline_avg_hourly_bytes": 5000
}
```

---

### Task 8: Protocol Audit Endpoint

**Files:**
- Modify: `daemon/services/iot_monitor.py` (add `get_protocol_audit`)
- Modify: `daemon/api/iot.py` (add handler + route)

**Implementation:**
1. Load `daemon/data/protocol_profiles.json` on startup
2. For each IoT device, query conn logs for ports used
3. Match device category (from manufacturer) to profile
4. Flag ports not in expected set
5. Check for: Telnet (23), unencrypted MQTT (1883), SSH (22) on non-hub devices
6. Check for hardcoded DNS: conn logs where `destination.port=53` AND `destination.ip` not in local DNS

**Endpoint:** `GET /api/iot/protocol-audit?from=&to=`

---

### Task 9: Network Isolation Endpoint

**Files:**
- Modify: `daemon/services/iot_monitor.py` (add `get_network_isolation`)
- Modify: `daemon/api/iot.py` (add handler + route)

**Implementation:**
1. Get all IoT device MACs
2. Query conn logs where `source.mac` in IoT MACs AND `destination.ip` is RFC1918
3. Cross-reference destination IPs against device registry to find device types
4. Classify: IoT→workstation (critical), IoT→NAS (high), IoT→IoT (info)
5. Compute segmentation score

**Endpoint:** `GET /api/iot/network-isolation?from=&to=`

---

### Task 10: Manufacturer Profiles Endpoint

**Files:**
- Modify: `daemon/services/iot_monitor.py` (add `get_manufacturer_profiles`)
- Modify: `daemon/api/iot.py` (add handler + route)

**Implementation:**
1. Group IoT devices by manufacturer
2. For each manufacturer, aggregate: device count, avg trust score, avg privacy grade
3. Query for encryption ratio, tracker count, protocol violations across all devices of that manufacturer
4. Sort by worst hygiene first

**Endpoint:** `GET /api/iot/manufacturer-profiles?from=&to=`

---

## Phase 3: Frontend — API Client & Types

### Task 11: IoT Trust Score API Client

**Files:**
- Modify: `web/src/lib/api/iot.ts` (add new types + fetch functions)
- Modify: `web/src/lib/api/iot.test.ts` (add tests for new functions)

**Step 1: Write failing tests**

Add to `web/src/lib/api/iot.test.ts`:

```typescript
describe('getFleetSummary', () => {
    it('returns fleet summary on success', async () => {
        mockFetchSuccess({
            health_score: 85,
            health_grade: 'B',
            device_count: 5,
            anomaly_count: 2,
            privacy_concerns: 1,
            unencrypted_count: 0,
            devices: [],
        });
        const result = await getFleetSummary();
        expect(result.health_score).toBe(85);
        expect(result.health_grade).toBe('B');
    });

    it('returns defaults on failure', async () => {
        mockFetchFailure();
        const result = await getFleetSummary();
        expect(result.health_score).toBe(0);
        expect(result.devices).toEqual([]);
    });
});

describe('getPrivacyReport', () => {
    it('returns privacy report on success', async () => {
        mockFetchSuccess({ devices: [{ mac: 'AA:BB:CC:DD:EE:FF', privacy_grade: 'B', tracker_count: 3 }] });
        const result = await getPrivacyReport();
        expect(result.devices).toHaveLength(1);
    });
});

describe('getCommunicationMap', () => {
    it('returns destinations for a device', async () => {
        mockFetchSuccess({ mac: 'AA:BB:CC:DD:EE:FF', destinations: [{ ip: '1.2.3.4', in_baseline: true }] });
        const result = await getCommunicationMap('AA:BB:CC:DD:EE:FF');
        expect(result.destinations).toHaveLength(1);
    });
});

describe('getActivityTimeline', () => {
    it('returns hourly buckets', async () => {
        mockFetchSuccess({ mac: 'AA:BB:CC:DD:EE:FF', buckets: [{ time: '2026-04-04T00:00:00Z', connections: 5 }] });
        const result = await getActivityTimeline('AA:BB:CC:DD:EE:FF');
        expect(result.buckets).toHaveLength(1);
    });
});
```

**Step 2: Run tests — expect FAIL**

Run: `cd web && npx vitest run src/lib/api/iot.test.ts`

**Step 3: Add types and fetch functions to `web/src/lib/api/iot.ts`**

New types: `FleetSummary`, `FleetDevice`, `PrivacyReport`, `PrivacyDevice`, `CommunicationMap`, `Destination`, `ActivityTimeline`, `TimelineBucket`, `ProtocolAudit`, `ProtocolFinding`, `NetworkIsolation`, `IsolationPair`, `ManufacturerProfile`

New functions: `getFleetSummary()`, `getPrivacyReport()`, `getCommunicationMap(mac)`, `getActivityTimeline(mac)`, `getProtocolAudit()`, `getNetworkIsolation()`, `getManufacturerProfiles()`

**Step 4: Run tests — expect PASS**

**Step 5: Commit**

```bash
git commit -m "feat(iot): add trust score API client types and fetch helpers"
```

---

## Phase 4: Frontend — IoT Page

### Task 12: IoT Page — Hero Score + Stat Cards

**Files:**
- Modify: `web/src/routes/iot/+page.svelte` (full rewrite)

**Implementation:**
- SVG gauge arc (reuse pattern from threats page `web/src/routes/threats/+page.svelte`)
- 3 sub-score badges (Privacy, Security, Behavior) with color coding
- Plain-English subtitle
- 4 stat cards: IoT Devices, Anomalies, Privacy Concerns, Unencrypted
- Time range pills (1h, 6h, 24h, 7d)
- Auto-fetch on mount + range change via `$effect()`

**Key patterns to reuse:**
- Gauge arc path: `web/src/routes/threats/+page.svelte` (search for `gaugeArcPath`)
- Stat cards: global `.stat-card` class
- Time pills: global `.pill` class

---

### Task 13: IoT Page — Device Trust Grid

**Files:**
- Modify: `web/src/routes/iot/+page.svelte` (add device grid section)

**Implementation:**
- 4-column responsive grid of device cards
- Each card: device name, trust grade badge, mini indicators, last seen
- Cards sorted by trust score ascending (worst first)
- Click → set selectedDevice state → open detail drawer
- Color coding per grade: A=green, B=cyan, C=amber, D=orange, F=red
- Hover animation (translateY -2px, box-shadow)

**Key patterns to reuse:**
- Device card layout: `web/src/routes/devices/+page.svelte` (search for `.device-card`)

---

### Task 14: IoT Page — Device Detail Drawer (5 tabs)

**Files:**
- Modify: `web/src/routes/iot/+page.svelte` (add drawer with 5 tabs)

**Implementation:**
- Use `DetailDrawer` component with 5 tabs
- Tab 1 (Overview): Trust score breakdown, device info via KVRow, quick stats
- Tab 2 (Communication Map): HorizontalBarList of destinations with `in_baseline` badges
- Tab 3 (Privacy): Privacy grade, tracker domains list (HorizontalBarList), DonutChart for encryption ratio
- Tab 4 (Protocol Audit): Table of protocols with Expected/Unexpected badges
- Tab 5 (Activity Timeline): TimeSeriesChart with baseline overlay

**Key components:**
- `import DetailDrawer from '$lib/components/DetailDrawer.svelte'`
- `import HorizontalBarList from '$lib/components/HorizontalBarList.svelte'`
- `import DonutChart from '$lib/components/charts/DonutChart.svelte'`
- `import TimeSeriesChart from '$lib/components/charts/TimeSeriesChart.svelte'`
- `import KVRow from '$lib/components/drawer/KVRow.svelte'`
- `import DrawerSection from '$lib/components/drawer/DrawerSection.svelte'`

---

### Task 15: IoT Page — Manufacturer Profiles + Findings Feed + Network Isolation

**Files:**
- Modify: `web/src/routes/iot/+page.svelte` (add remaining sections)

**Implementation:**
- Manufacturer Profiles card: grouped by manufacturer, HorizontalBarList for hygiene scores
- Findings Feed: chronological feed with severity badges, plain-English descriptions, category tags
- Network Isolation card: table of IoT→LAN pairs with risk badges, segmentation score, recommendation text

---

## Phase 5: Tests & Verification

### Task 16: Frontend Page Test

**Files:**
- Create: `web/src/routes/iot/iot.test.ts`

**Implementation:** Test that the page renders with mock data:
- Hero score displays
- Stat cards render
- Device grid renders device cards
- Clicking a device opens the detail drawer
- Empty state renders when no IoT devices

**Pattern to follow:** `web/src/routes/devices/devices.test.ts`

---

### Task 17: Full Verification Sweep

**Step 1:** Run backend tests

```bash
cd daemon && python -m pytest -v
```

Expected: All pass

**Step 2:** Run frontend tests

```bash
cd web && npx vitest run
```

Expected: All pass

**Step 3:** Run type check

```bash
cd web && npx svelte-check
```

Expected: No errors

**Step 4:** Build check

```bash
cd web && npm run build
```

Expected: Clean build

---

## File Index

| File | Action | Task |
|------|--------|------|
| `daemon/data/tracker_domains.txt` | Create | 1 |
| `daemon/data/protocol_profiles.json` | Create | 2 |
| `daemon/services/iot_trust_scorer.py` | Create | 3 |
| `daemon/tests/test_iot_trust_scorer.py` | Create | 3 |
| `daemon/services/iot_monitor.py` | Modify | 4-10 |
| `daemon/api/iot.py` | Modify | 4-10 |
| `daemon/tests/test_iot_monitor.py` | Modify | 4-10 |
| `web/src/lib/api/iot.ts` | Modify | 11 |
| `web/src/lib/api/iot.test.ts` | Modify | 11 |
| `web/src/routes/iot/+page.svelte` | Rewrite | 12-15 |
| `web/src/routes/iot/iot.test.ts` | Create | 16 |
