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
