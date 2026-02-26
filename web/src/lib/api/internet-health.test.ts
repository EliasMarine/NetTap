import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getInternetHealth,
	getInternetHistory,
	getInternetStats,
	triggerHealthCheck,
} from './internet-health';

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

const sampleCheck = {
	timestamp: '2026-02-26T12:00:00Z',
	latency_ms: 12.5,
	dns_resolve_ms: 5.2,
	packet_loss_pct: 0,
	status: 'healthy',
};

const sampleStats = {
	avg_latency_ms: 15.3,
	p95_latency_ms: 45.0,
	min_latency_ms: 5.1,
	max_latency_ms: 120.0,
	avg_dns_ms: 8.2,
	avg_packet_loss_pct: 0.5,
	uptime_pct: 99.8,
	total_checks: 1440,
	history_span_hours: 24,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('internet-health API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getInternetHealth ----------------------------------------------------

	describe('getInternetHealth', () => {
		it('returns parsed health check on success', async () => {
			mockFetchSuccess(sampleCheck);

			const result = await getInternetHealth();

			expect(fetch).toHaveBeenCalledWith('/api/internet/health');
			expect(result.status).toBe('healthy');
			expect(result.latency_ms).toBe(12.5);
		});

		it('returns down status on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getInternetHealth();

			expect(result.status).toBe('down');
			expect(result.latency_ms).toBeNull();
			expect(result.packet_loss_pct).toBe(100);
		});

		it('returns dns_resolve_ms from the check', async () => {
			mockFetchSuccess(sampleCheck);

			const result = await getInternetHealth();

			expect(result.dns_resolve_ms).toBe(5.2);
		});
	});

	// -- getInternetHistory ---------------------------------------------------

	describe('getInternetHistory', () => {
		it('returns parsed history on success', async () => {
			const expected = { history: [sampleCheck] };
			mockFetchSuccess(expected);

			const result = await getInternetHistory();

			expect(fetch).toHaveBeenCalledWith('/api/internet/history');
			expect(result.history).toHaveLength(1);
			expect(result.history[0].status).toBe('healthy');
		});

		it('passes limit query parameter when provided', async () => {
			mockFetchSuccess({ history: [] });

			await getInternetHistory(100);

			const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('limit=100');
		});

		it('returns empty history on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getInternetHistory();

			expect(result.history).toEqual([]);
		});

		it('returns multiple history entries', async () => {
			const degradedCheck = { ...sampleCheck, status: 'degraded', latency_ms: 95.0 };
			mockFetchSuccess({ history: [sampleCheck, degradedCheck] });

			const result = await getInternetHistory();

			expect(result.history).toHaveLength(2);
			expect(result.history[1].status).toBe('degraded');
		});
	});

	// -- getInternetStats -----------------------------------------------------

	describe('getInternetStats', () => {
		it('returns parsed stats on success', async () => {
			mockFetchSuccess(sampleStats);

			const result = await getInternetStats();

			expect(fetch).toHaveBeenCalledWith('/api/internet/stats');
			expect(result.uptime_pct).toBe(99.8);
			expect(result.total_checks).toBe(1440);
		});

		it('returns zeroed stats on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getInternetStats();

			expect(result.avg_latency_ms).toBe(0);
			expect(result.uptime_pct).toBe(0);
			expect(result.total_checks).toBe(0);
			expect(result.avg_packet_loss_pct).toBe(100);
		});

		it('includes p95 and min/max latency', async () => {
			mockFetchSuccess(sampleStats);

			const result = await getInternetStats();

			expect(result.p95_latency_ms).toBe(45.0);
			expect(result.min_latency_ms).toBe(5.1);
			expect(result.max_latency_ms).toBe(120.0);
		});
	});

	// -- triggerHealthCheck ----------------------------------------------------

	describe('triggerHealthCheck', () => {
		it('sends POST request and returns result', async () => {
			mockFetchSuccess(sampleCheck);

			const result = await triggerHealthCheck();

			expect(fetch).toHaveBeenCalledWith('/api/internet/check', { method: 'POST' });
			expect(result.status).toBe('healthy');
			expect(result.latency_ms).toBe(12.5);
		});

		it('returns down status on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await triggerHealthCheck();

			expect(result.status).toBe('down');
			expect(result.packet_loss_pct).toBe(100);
		});
	});
});
