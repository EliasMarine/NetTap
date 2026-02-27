import { describe, it, expect, vi, afterEach } from 'vitest';
import { getAlerts, getAlertCount } from './alerts';

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
// Tests
// ---------------------------------------------------------------------------

describe('alerts API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getAlertCount -------------------------------------------------------

	describe('getAlertCount', () => {
		it('returns parsed alert counts on success', async () => {
			const expected = {
				from: '2026-02-25T00:00:00Z',
				to: '2026-02-26T00:00:00Z',
				counts: { total: 42, high: 3, medium: 15, low: 24 },
			};
			mockFetchSuccess(expected);

			const result = await getAlertCount();

			expect(fetch).toHaveBeenCalledWith('/api/alerts/count');
			expect(result.counts.total).toBe(42);
			expect(result.counts.high).toBe(3);
		});

		it('returns zero counts on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getAlertCount();

			expect(result.counts.total).toBe(0);
			expect(result.counts.high).toBe(0);
			expect(result.counts.medium).toBe(0);
			expect(result.counts.low).toBe(0);
		});

		it('passes time range parameters', async () => {
			mockFetchSuccess({ from: '', to: '', counts: { total: 0, high: 0, medium: 0, low: 0 } });

			await getAlertCount({ from: '2026-02-25T00:00:00Z' });

			expect(fetch).toHaveBeenCalledWith(
				expect.stringContaining('/api/alerts/count?')
			);
		});
	});

	// -- getAlerts -----------------------------------------------------------

	describe('getAlerts', () => {
		it('returns parsed alert list on success', async () => {
			const expected = {
				from: '',
				to: '',
				page: 1,
				size: 10,
				total: 2,
				total_pages: 1,
				alerts: [
					{
						_id: 'abc123',
						_index: 'suricata-2026.02',
						timestamp: '2026-02-26T12:00:00Z',
						alert: { signature: 'ET MALWARE Test', severity: 1, category: 'Malware' },
						src_ip: '10.0.0.5',
						src_port: 12345,
						dest_ip: '93.184.216.34',
						dest_port: 443,
						proto: 'TCP',
						acknowledged: false,
					},
				],
			};
			mockFetchSuccess(expected);

			const result = await getAlerts({ size: 10 });

			expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/alerts'));
			expect(result.alerts).toHaveLength(1);
			expect(result.alerts[0].alert?.signature).toBe('ET MALWARE Test');
		});

		it('returns empty list on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getAlerts();

			expect(result.alerts).toEqual([]);
			expect(result.total).toBe(0);
		});

		it('passes severity filter', async () => {
			mockFetchSuccess({ from: '', to: '', page: 1, size: 50, total: 0, total_pages: 0, alerts: [] });

			await getAlerts({ severity: 1 });

			const fetchCall = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(fetchCall).toContain('severity=1');
		});
	});
});
