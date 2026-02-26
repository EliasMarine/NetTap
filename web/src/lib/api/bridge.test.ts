import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getBridgeHealth,
	getBridgeHistory,
	getBridgeStats,
	enableBypass,
	disableBypass,
	getBypassStatus,
} from './bridge';

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

function mockFetchSuccess(body: unknown, status = 200): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: status >= 200 && status < 300,
			status,
			json: () => Promise.resolve(body),
		}),
	);
}

function mockFetchFailure(status = 500): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => Promise.reject(new Error('no body')),
		}),
	);
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

const sampleHealth = {
	bridge_state: 'up' as const,
	wan_link: true,
	lan_link: true,
	bypass_active: false,
	watchdog_active: true,
	latency_us: 42,
	rx_bytes_delta: 1024000,
	tx_bytes_delta: 512000,
	rx_packets_delta: 850,
	tx_packets_delta: 420,
	uptime_seconds: 86400,
	health_status: 'normal' as const,
	issues: [],
	last_check: '2026-02-26T12:00:00Z',
};

const sampleStats = {
	avg_latency_us: 38,
	total_rx_packets: 1_000_000,
	total_tx_packets: 500_000,
	uptime_percent: 99.95,
	longest_downtime_seconds: 12,
	check_count: 5760,
};

const sampleBypassStatus = {
	active: false,
	activated_at: null,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('bridge API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getBridgeHealth -------------------------------------------------------

	describe('getBridgeHealth', () => {
		it('returns parsed bridge health on success', async () => {
			mockFetchSuccess(sampleHealth);

			const result = await getBridgeHealth();

			expect(fetch).toHaveBeenCalledWith('/api/bridge/health');
			expect(result.bridge_state).toBe('up');
			expect(result.wan_link).toBe(true);
			expect(result.lan_link).toBe(true);
			expect(result.latency_us).toBe(42);
			expect(result.health_status).toBe('normal');
		});

		it('returns default values on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getBridgeHealth();

			expect(result.bridge_state).toBe('unknown');
			expect(result.wan_link).toBe(false);
			expect(result.lan_link).toBe(false);
			expect(result.health_status).toBe('down');
			expect(result.issues).toContain('Unable to reach bridge health endpoint');
		});

		it('returns default values on server error', async () => {
			mockFetchFailure(500);

			const result = await getBridgeHealth();

			expect(result.bridge_state).toBe('unknown');
			expect(result.uptime_seconds).toBe(0);
			expect(result.latency_us).toBe(0);
		});

		it('includes issues array from response', async () => {
			const healthWithIssues = { ...sampleHealth, issues: ['WAN link flapping', 'High latency detected'] };
			mockFetchSuccess(healthWithIssues);

			const result = await getBridgeHealth();

			expect(result.issues).toHaveLength(2);
			expect(result.issues[0]).toBe('WAN link flapping');
		});

		it('reports bypass_active and watchdog_active booleans', async () => {
			const bypassHealth = { ...sampleHealth, bypass_active: true, watchdog_active: false };
			mockFetchSuccess(bypassHealth);

			const result = await getBridgeHealth();

			expect(result.bypass_active).toBe(true);
			expect(result.watchdog_active).toBe(false);
		});
	});

	// -- getBridgeHistory ------------------------------------------------------

	describe('getBridgeHistory', () => {
		it('returns history array on success', async () => {
			const expected = { history: [sampleHealth, { ...sampleHealth, latency_us: 55 }] };
			mockFetchSuccess(expected);

			const result = await getBridgeHistory();

			expect(fetch).toHaveBeenCalledWith('/api/bridge/history');
			expect(result.history).toHaveLength(2);
			expect(result.history[0].latency_us).toBe(42);
			expect(result.history[1].latency_us).toBe(55);
		});

		it('passes limit parameter in query string', async () => {
			mockFetchSuccess({ history: [sampleHealth] });

			await getBridgeHistory(50);

			expect(fetch).toHaveBeenCalledWith('/api/bridge/history?limit=50');
		});

		it('returns empty history on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getBridgeHistory();

			expect(result.history).toEqual([]);
		});
	});

	// -- getBridgeStats --------------------------------------------------------

	describe('getBridgeStats', () => {
		it('returns parsed stats on success', async () => {
			mockFetchSuccess(sampleStats);

			const result = await getBridgeStats();

			expect(fetch).toHaveBeenCalledWith('/api/bridge/stats');
			expect(result.avg_latency_us).toBe(38);
			expect(result.uptime_percent).toBe(99.95);
			expect(result.check_count).toBe(5760);
		});

		it('returns default stats on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getBridgeStats();

			expect(result.avg_latency_us).toBe(0);
			expect(result.uptime_percent).toBe(0);
			expect(result.total_rx_packets).toBe(0);
			expect(result.total_tx_packets).toBe(0);
		});

		it('returns complete stat fields', async () => {
			mockFetchSuccess(sampleStats);

			const result = await getBridgeStats();

			expect(result.total_rx_packets).toBe(1_000_000);
			expect(result.total_tx_packets).toBe(500_000);
			expect(result.longest_downtime_seconds).toBe(12);
		});
	});

	// -- enableBypass ----------------------------------------------------------

	describe('enableBypass', () => {
		it('calls POST correctly and returns result', async () => {
			mockFetchSuccess({ result: 'ok' });

			const result = await enableBypass();

			expect(fetch).toHaveBeenCalledWith('/api/bridge/bypass/enable', { method: 'POST' });
			expect(result.result).toBe('ok');
		});

		it('returns error result on HTTP failure', async () => {
			mockFetchFailure(500);

			const result = await enableBypass();

			expect(result.result).toBe('error');
		});
	});

	// -- disableBypass ---------------------------------------------------------

	describe('disableBypass', () => {
		it('calls POST correctly and returns result', async () => {
			mockFetchSuccess({ result: 'ok' });

			const result = await disableBypass();

			expect(fetch).toHaveBeenCalledWith('/api/bridge/bypass/disable', { method: 'POST' });
			expect(result.result).toBe('ok');
		});

		it('returns error result on HTTP failure', async () => {
			mockFetchFailure(500);

			const result = await disableBypass();

			expect(result.result).toBe('error');
		});
	});

	// -- getBypassStatus -------------------------------------------------------

	describe('getBypassStatus', () => {
		it('returns parsed bypass status on success', async () => {
			mockFetchSuccess(sampleBypassStatus);

			const result = await getBypassStatus();

			expect(fetch).toHaveBeenCalledWith('/api/bridge/bypass/status');
			expect(result.active).toBe(false);
			expect(result.activated_at).toBeNull();
		});

		it('returns active bypass status with timestamp', async () => {
			const activeBypass = { active: true, activated_at: '2026-02-26T10:00:00Z' };
			mockFetchSuccess(activeBypass);

			const result = await getBypassStatus();

			expect(result.active).toBe(true);
			expect(result.activated_at).toBe('2026-02-26T10:00:00Z');
		});

		it('returns default bypass status on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getBypassStatus();

			expect(result.active).toBe(false);
			expect(result.activated_at).toBeNull();
		});
	});
});
