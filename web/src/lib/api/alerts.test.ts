import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getAlerts,
	getAlertCount,
	getAlertTimeline,
	getAlertTopSignatures,
	getAlertTopIps,
	getAlertCategories,
	formatNumber,
	severityLabel,
	severityBadgeClass,
} from './alerts';

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

	// -- getAlertTimeline ----------------------------------------------------

	describe('getAlertTimeline', () => {
		it('returns timeline buckets on success', async () => {
			const expected = {
				from: '', to: '', interval: '1h',
				buckets: [{ timestamp: '2026-03-09T00:00:00Z', high: 3, medium: 12, low: 41 }],
			};
			mockFetchSuccess(expected);

			const result = await getAlertTimeline({ interval: '1h' });
			expect(result.buckets).toHaveLength(1);
			expect(result.buckets[0].high).toBe(3);
		});

		it('returns empty buckets on error', async () => {
			mockFetchFailure(502);
			const result = await getAlertTimeline();
			expect(result.buckets).toEqual([]);
		});

		it('includes interval in URL', async () => {
			mockFetchSuccess({ from: '', to: '', interval: '5m', buckets: [] });
			await getAlertTimeline({ interval: '5m' });
			const url = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('interval=5m');
		});
	});

	// -- getAlertTopSignatures ------------------------------------------------

	describe('getAlertTopSignatures', () => {
		it('returns signatures on success', async () => {
			const expected = {
				from: '', to: '',
				signatures: [{ signature: 'ET SCAN Nmap', count: 42, severity: 2 }],
			};
			mockFetchSuccess(expected);

			const result = await getAlertTopSignatures({ limit: 10 });
			expect(result.signatures).toHaveLength(1);
			expect(result.signatures[0].count).toBe(42);
		});

		it('returns empty on error', async () => {
			mockFetchFailure(502);
			const result = await getAlertTopSignatures();
			expect(result.signatures).toEqual([]);
		});

		it('includes limit in URL', async () => {
			mockFetchSuccess({ from: '', to: '', signatures: [] });
			await getAlertTopSignatures({ limit: 5 });
			const url = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('limit=5');
		});
	});

	// -- getAlertTopIps -------------------------------------------------------

	describe('getAlertTopIps', () => {
		it('returns IPs on success', async () => {
			const expected = {
				from: '', to: '', direction: 'dest',
				ips: [{ ip: '192.168.1.5', count: 37 }],
			};
			mockFetchSuccess(expected);

			const result = await getAlertTopIps({ direction: 'dest' });
			expect(result.ips).toHaveLength(1);
			expect(result.ips[0].ip).toBe('192.168.1.5');
		});

		it('returns empty on error', async () => {
			mockFetchFailure(502);
			const result = await getAlertTopIps();
			expect(result.ips).toEqual([]);
		});

		it('includes direction in URL', async () => {
			mockFetchSuccess({ from: '', to: '', direction: 'src', ips: [] });
			await getAlertTopIps({ direction: 'src' });
			const url = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('direction=src');
		});
	});

	// -- getAlertCategories ---------------------------------------------------

	describe('getAlertCategories', () => {
		it('returns categories on success', async () => {
			const expected = {
				from: '', to: '',
				categories: [{ category: 'Attempted Information Leak', count: 88 }],
			};
			mockFetchSuccess(expected);

			const result = await getAlertCategories();
			expect(result.categories).toHaveLength(1);
			expect(result.categories[0].count).toBe(88);
		});

		it('returns empty on error', async () => {
			mockFetchFailure(502);
			const result = await getAlertCategories();
			expect(result.categories).toEqual([]);
		});
	});

	// -- Formatting helpers ---------------------------------------------------

	describe('formatNumber', () => {
		it('formats small numbers', () => {
			expect(formatNumber(42)).toBe('42');
		});

		it('formats thousands', () => {
			expect(formatNumber(1500)).toBe('1.5K');
		});

		it('formats millions', () => {
			expect(formatNumber(2500000)).toBe('2.5M');
		});
	});

	describe('severityLabel', () => {
		it('returns HIGH for 1', () => {
			expect(severityLabel(1)).toBe('HIGH');
		});

		it('returns INFO for undefined', () => {
			expect(severityLabel(undefined)).toBe('INFO');
		});
	});

	describe('severityBadgeClass', () => {
		it('returns severity-high for 1', () => {
			expect(severityBadgeClass(1)).toBe('badge severity-high');
		});

		it('returns severity-info for undefined', () => {
			expect(severityBadgeClass(undefined)).toBe('badge severity-info');
		});
	});
});
