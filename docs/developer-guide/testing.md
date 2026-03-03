# Testing

NetTap uses pytest for the Python daemon and Vitest for the web dashboard. All tests must pass before a PR can be merged.

---

## Running All Tests

```bash
# Run everything
cd daemon && python -m pytest && cd ../web && npx vitest run && npx svelte-check
```

---

## Python Daemon Tests (pytest)

### Running

```bash
cd daemon

# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ -v --cov=. --cov-report=term-missing

# Run a specific test file
python -m pytest tests/test_storage.py -v

# Run a specific test
python -m pytest tests/test_storage.py::test_disk_threshold -v
```

### Test Structure

```
daemon/tests/
  test_storage.py         StorageManager unit tests
  test_smart.py           SmartMonitor unit tests
  test_api_server.py      API endpoint tests
  test_traffic.py         Traffic analysis tests
  test_alerts.py          Alert management tests
  test_devices.py         Device inventory tests
  ...
```

### Writing Daemon Tests

Tests use pytest fixtures to mock external dependencies (OpenSearch, disk I/O, SMART data):

```python title="Example test pattern"
import pytest
from unittest.mock import MagicMock, patch
from storage.manager import StorageManager, RetentionConfig


@pytest.fixture
def mock_config():
    return RetentionConfig(
        hot_days=90,
        warm_days=180,
        cold_days=30,
        disk_threshold=0.80,
        emergency_threshold=0.90,
    )


@pytest.fixture
def mock_storage(mock_config):
    with patch("storage.manager.OpenSearch") as mock_os:
        storage = StorageManager(mock_config, "http://localhost:9200")
        yield storage


def test_disk_threshold(mock_storage):
    """Storage manager should trigger pruning above threshold."""
    # ... test implementation
```

### Key Testing Patterns

- **Mock OpenSearch** --- never connect to a real cluster in tests
- **Mock disk I/O** --- use `unittest.mock.patch` for `shutil.disk_usage`
- **Mock SMART** --- provide canned `smartctl` output
- **Test error handling** --- verify behavior when OpenSearch is unreachable, disk is full, etc.
- **Test query building** --- verify that API parameters produce correct OpenSearch queries

---

## Web Dashboard Tests (Vitest)

### Running

```bash
cd web

# Run all tests
npx vitest run

# Run in watch mode (re-runs on file changes)
npx vitest

# Run a specific test file
npx vitest run src/lib/components/TimeSeriesChart.test.ts

# Run with coverage
npx vitest run --coverage
```

### Type Checking

```bash
cd web

# Run svelte-check for TypeScript errors
npx svelte-check
```

### Test Structure

Tests are co-located with their source files using `.test.ts` or `.spec.ts` suffixes:

```
web/src/
  lib/
    components/
      TimeSeriesChart.svelte
      TimeSeriesChart.test.ts     # Component test
  api/
    traffic.ts
    traffic.test.ts               # API client test
```

### Writing Web Tests

#### API Client Tests

Test that API client functions construct correct requests and handle responses:

```typescript title="Example API test"
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getTrafficSummary } from './traffic';

describe('getTrafficSummary', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('fetches traffic summary with default params', async () => {
    const mockResponse = { total_bytes: 1000, connection_count: 50 };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse),
    });

    const result = await getTrafficSummary();
    expect(result).toEqual(mockResponse);
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/traffic/summary'),
      expect.anything()
    );
  });

  it('handles API errors gracefully', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));
    await expect(getTrafficSummary()).rejects.toThrow('Network error');
  });
});
```

#### Component Tests

Test component rendering with mock data using Vitest and Testing Library:

```typescript title="Example component test"
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import MyComponent from './MyComponent.svelte';

describe('MyComponent', () => {
  it('renders with data', () => {
    render(MyComponent, { props: { data: mockData } });
    expect(screen.getByText('Expected Text')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    render(MyComponent, { props: { loading: true } });
    expect(screen.getByTestId('skeleton')).toBeInTheDocument();
  });

  it('shows empty state', () => {
    render(MyComponent, { props: { data: [] } });
    expect(screen.getByText('No data available')).toBeInTheDocument();
  });
});
```

### Key Testing Patterns

- **Mock fetch** --- never make real API calls in tests
- **Test all states** --- loading, data, empty, error
- **Test interactions** --- click handlers, form submissions
- **Test accessibility** --- keyboard navigation, ARIA attributes

---

## Shell Script Linting

```bash
# Lint all shell scripts
shellcheck scripts/**/*.sh

# Lint a specific script
shellcheck scripts/install/install.sh
```

ShellCheck catches common shell scripting errors like unquoted variables, missing error handling, and portability issues.

---

## CI Integration

All tests run automatically in GitHub Actions on every push and PR:

1. **Python tests:** `cd daemon && python -m pytest`
2. **Web tests:** `cd web && npx vitest run`
3. **Type checking:** `cd web && npx svelte-check`
4. **Shell linting:** `shellcheck scripts/**/*.sh`

A PR cannot be merged until all CI checks pass.

---

## Test Coverage Requirements

- **New features** must include tests for both the daemon API layer and the web UI layer
- **Bug fixes** should include a regression test that would have caught the bug
- **Daemon tests** must mock OpenSearch (never connect to a real cluster)
- **Web tests** must mock fetch (never make real API calls)
- **Component tests** must cover loading, data, empty, and error states

---

## v1.0 Release Verification

NetTap includes an automated release verification script that checks code quality, tests, and build integrity.

### Quick Check (CI-friendly)

Runs secrets audit, linting, tests, and type checking (~2-5 minutes):

```bash
cd ~/NetTap
./scripts/verify-release.sh --quick
```

### Full Verification

Includes Docker builds, Trivy CVE scanning, and E2E tests (~15-30 minutes):

```bash
cd ~/NetTap
./scripts/verify-release.sh --full
```

### Other Modes

```bash
# Secrets audit only
./scripts/verify-release.sh --secrets-only

# Quick checks + Docker builds
./scripts/verify-release.sh --docker

# Quick checks + Docker builds + Trivy scan
./scripts/verify-release.sh --trivy

# Verbose output (show full command output)
./scripts/verify-release.sh --quick -v
```

---

## Deployment Verification (Target Hardware)

These commands verify a full deployment on reference hardware (Intel N100 or similar).

### 1. Clean Install

```bash
# On target host — fresh install
cd /opt/nettap
sudo scripts/install/install.sh

# Verify all containers are healthy
sudo docker ps --format "table {{.Names}}\t{{.Status}}"
```

### 2. Container Health Checks

```bash
# Check each core service is responding
curl -sf http://localhost:8880/api/health | python3 -m json.tool        # Daemon API
curl -sk https://localhost:443/ -o /dev/null -w "HTTP %{http_code}\n"   # Web dashboard
curl -sf http://localhost:9200/_cluster/health | python3 -m json.tool   # OpenSearch
```

### 3. Dashboard Load Timing

Target: page loads in < 3 seconds on LAN.

```bash
# Measure full page load time
curl -sk -o /dev/null -w "Total: %{time_total}s\nTTFB: %{time_starttransfer}s\n" https://localhost:443/
```

### 4. Bridge Throughput

Target: 500Mbps sustained with zero packet loss.

```bash
# On a machine behind the bridge, run iperf3 against the router/upstream
# Server side (on router or upstream machine):
iperf3 -s

# Client side (on machine behind bridge):
iperf3 -c <router-ip> -t 60 -P 4
# Expect: ~500+ Mbps, 0% packet loss
```

### 5. Alert Latency Test

Target: Suricata alerts appear in < 10 seconds.

```bash
# Trigger a known ET rule (e.g., ICMP to external host)
ping -c 1 8.8.8.8

# Check for alert in OpenSearch (within 10 seconds)
curl -sf 'http://localhost:9200/suricata-*/_search?size=1&sort=timestamp:desc' \
  | python3 -m json.tool | head -20
```

### 6. Storage Pruning Verification

Target: daemon prunes at 80% disk threshold.

```bash
# Check current disk usage and daemon pruning config
curl -sf http://localhost:8880/api/storage/status | python3 -m json.tool

# View daemon logs for pruning activity
sudo docker logs nettap-storage-daemon 2>&1 | grep -i prune | tail -10
```
