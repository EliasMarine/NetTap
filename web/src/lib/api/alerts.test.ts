import { describe, it, expect, vi, afterEach } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import {
	getAlerts,
	getAlertCount,
	getAlertTimeline,
	getAlertTopSignatures,
	getAlertTopIps,
	getAlertCategories,
	getEnhancedCategories,
	suppressAlert,
	markFalsePositive,
	formatNumber,
	severityLabel,
	severityBadgeClass,
	scoreInputs,
} from './alerts';
import type { BaselineInfo } from './threats';

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

		// #96: zero counts read as "no alerts"
		it('throws on HTTP error', async () => {
			mockFetchFailure(502);

			await expect(getAlertCount()).rejects.toThrow('HTTP 502');
		});

		it('passes time range parameters', async () => {
			mockFetchSuccess({ from: '', to: '', counts: { total: 0, high: 0, medium: 0, low: 0 } });

			await getAlertCount({ from: '2026-02-25T00:00:00Z' });

			expect(fetch).toHaveBeenCalledWith(
				expect.stringContaining('/api/alerts/count?')
			);
		});

		it('counts the activity alerts only when asked (NET-191)', async () => {
			mockFetchSuccess({ from: '', to: '', counts: { total: 0, high: 0, medium: 0, low: 0 } });
			await getAlertCount({ from: 'a', to: 'b', activity: true });
			await getAlertCount({ from: 'a', to: 'b', activity: false });
			expect(fetch).toHaveBeenNthCalledWith(1, '/api/alerts/count?from=a&to=b&activity=true');
			expect(fetch).toHaveBeenNthCalledWith(2, '/api/alerts/count?from=a&to=b');
		});
	});

	// -- getAlerts -----------------------------------------------------------

	describe('getAlerts', () => {
		it('sends the sort and order so the daemon sorts every page (#146)', async () => {
			mockFetchSuccess({ alerts: [] });
			await getAlerts({ page: 2, size: 50, sort: 'severity', order: 'desc' });
			expect(fetch).toHaveBeenCalledWith('/api/alerts?page=2&size=50&sort=severity&order=desc');
		});

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

		// #96: an empty list read as "No Alerts"
		it('throws on HTTP error', async () => {
			mockFetchFailure(500);

			await expect(getAlerts()).rejects.toThrow('HTTP 500');
		});

		it('passes severity filter', async () => {
			mockFetchSuccess({ from: '', to: '', page: 1, size: 50, total: 0, total_pages: 0, alerts: [] });

			await getAlerts({ severity: 1 });

			const fetchCall = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(fetchCall).toContain('severity=1');
		});

		it('passes the info severity filter (I1)', async () => {
			mockFetchSuccess({ from: '', to: '', page: 1, size: 50, total: 0, total_pages: 0, alerts: [] });
			await getAlerts({ severity: 'info' });
			const fetchCall = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(fetchCall).toContain('severity=info');
		});

		it("sends a smart alert's source and destination (NET-160 slice 2b-1)", async () => {
			mockFetchSuccess({ from: '', to: '', page: 1, size: 50, total: 0, total_pages: 0, alerts: [] });
			await getAlerts({ signature: 'ET SCAN x', src: '192.168.1.20', dst: '2001:db8::1' });
			const sent = new URL((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string, 'http://x').searchParams;
			expect([sent.get('signature'), sent.get('src'), sent.get('dst')]).toEqual(['ET SCAN x', '192.168.1.20', '2001:db8::1']);
		});

		it('sends one raw Suricata category, and leaves out an empty one (NET-160 slice 2b-2)', async () => {
			mockFetchSuccess({ from: '', to: '', page: 1, size: 50, total: 0, total_pages: 0, alerts: [] });
			await getAlerts({ suricata_category: 'A/B & C' });
			await getAlerts({ suricata_category: '' });
			const calls = (fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => new URL(c[0] as string, 'http://x').searchParams);
			expect(calls[0].get('suricata_category')).toBe('A/B & C');
			expect(calls[1].has('suricata_category')).toBe(false);
		});

		it('lists the activity alerts only when asked (NET-191)', async () => {
			mockFetchSuccess({ from: '', to: '', page: 1, size: 50, total: 0, total_pages: 0, alerts: [] });
			await getAlerts({ page: 1, activity: true });
			await getAlerts({ page: 1 });
			expect(fetch).toHaveBeenNthCalledWith(1, '/api/alerts?page=1&activity=true');
			expect(fetch).toHaveBeenNthCalledWith(2, '/api/alerts?page=1');
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

		it('throws on error', async () => {
			mockFetchFailure(502);
			await expect(getAlertTimeline()).rejects.toThrow('HTTP 502');
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

		it('throws on error', async () => {
			mockFetchFailure(502);
			await expect(getAlertTopSignatures()).rejects.toThrow('HTTP 502');
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

		it('throws on error', async () => {
			mockFetchFailure(502);
			await expect(getAlertTopIps()).rejects.toThrow('HTTP 502');
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

		it('throws on error', async () => {
			mockFetchFailure(502);
			await expect(getAlertCategories()).rejects.toThrow('HTTP 502');
		});
	});

	// -- suppressAlert / markFalsePositive ------------------------------------

	describe('suppressAlert', () => {
		it('resolves when the daemon accepts', async () => {
			mockFetchSuccess({ status: 'suppressed', signature_id: 2001 });

			await expect(suppressAlert(2001, '10.0.0.5')).resolves.toBeUndefined();
			const [url, init] = vi.mocked(fetch).mock.calls[0];
			expect(url).toBe('/api/alerts/suppress');
			expect(JSON.parse(String(init?.body))).toMatchObject({ signature_id: 2001, device_ip: '10.0.0.5' });
		});

		it('throws the daemon error on a non-OK response', async () => {
			mockFetchSuccess({ error: 'signature_id is required' }, 400);

			await expect(suppressAlert(0)).rejects.toThrow('signature_id is required');
		});

		it('throws with the status when the body is unreadable', async () => {
			mockFetchFailure(502);

			await expect(suppressAlert(2001)).rejects.toThrow('Suppress failed: 502');
		});
	});

	describe('markFalsePositive', () => {
		it('resolves when the daemon accepts', async () => {
			mockFetchSuccess({ status: 'marked_false_positive', signature_id: 2001 });

			await expect(markFalsePositive(2001)).resolves.toBeUndefined();
			expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/alerts/false-positive');
		});

		it('throws on a non-OK response', async () => {
			mockFetchFailure(500);

			await expect(markFalsePositive(2001)).rejects.toThrow('Mark false positive failed: 500');
		});
	});

	// -- getEnhancedCategories -------------------------------------------------

	describe('getEnhancedCategories', () => {
		/** Shape of one entry from daemon/api/alerts.py handle_alerts_categories */
		function daemonCategory(overrides: Record<string, unknown> = {}) {
			return {
				id: 'malware',
				label: 'Malware',
				icon: 'bug',
				color: 'red',
				description: 'Malware activity',
				count: 42,
				severity_breakdown: { critical: 2, high: 10, medium: 30, low: 0, info: 0 },
				trend: 'increasing',
				sparkline: [
					{ timestamp: '2026-10-29T10:00:00.000Z', count: 3 },
					{ timestamp: '2026-10-29T11:00:00.000Z', count: 9 },
				],
				sub_categories: [{ id: 'trojan', label: 'Trojan', count: 12 }],
				mitre_techniques: [],
				...overrides,
			};
		}

		it('maps the trend string to { direction, percentage: 0 }', async () => {
			mockFetchSuccess({ from: 'a', to: 'b', interval: '1h', categories: [daemonCategory()] });

			const { categories } = await getEnhancedCategories();

			expect(categories[0].trend).toEqual({ direction: 'increasing', percentage: 0 });
		});

		it('maps sparkline points to their counts', async () => {
			mockFetchSuccess({ from: 'a', to: 'b', categories: [daemonCategory()] });

			const { categories } = await getEnhancedCategories();

			expect(categories[0].sparkline).toEqual([3, 9]);
		});

		// NET-228: too few whole slots or alerts to compare halves
		it('keeps not_enough_data', async () => {
			mockFetchSuccess({ from: 'a', to: 'b', categories: [daemonCategory({ trend: 'not_enough_data' })] });
			const { categories } = await getEnhancedCategories();
			expect(categories[0].trend.direction).toBe('not_enough_data');
		});

		it('falls back to stable for an unknown trend and keeps other fields', async () => {
			mockFetchSuccess({ from: 'a', to: 'b', categories: [daemonCategory({ trend: 'sideways', sparkline: undefined })] });

			const { categories } = await getEnhancedCategories();

			expect(categories[0].trend.direction).toBe('stable');
			expect(categories[0].sparkline).toEqual([]);
			expect(categories[0]).toMatchObject({ id: 'malware', count: 42, sub_categories: [{ id: 'trojan' }] });
		});

		// #96: an empty list read as "No category data available"
		it('throws on HTTP error', async () => {
			mockFetchFailure(500);
			await expect(getEnhancedCategories()).rejects.toThrow('HTTP 500');
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

// ---------------------------------------------------------------------------
// NET-239: the score's hidden inputs, in words
// ---------------------------------------------------------------------------

describe('scoreInputs', () => {
	const SUPPRESSED = 'findings in this window were left out by your suppressions or false-positive marks.';
	const baseline = (over: Partial<BaselineInfo> = {}): BaselineInfo => ({
		deviation: 2.4,
		avg_events: 1234,
		avg_threat_score: 10,
		history_points: 7,
		is_anomalous: true,
		ready: true,
		earlier_hours: 6,
		...over,
	});

	it('counts the findings suppressions left out', () => {
		expect(scoreInputs({ suppressed_findings: 3 })).toEqual([`3 ${SUPPRESSED}`]);
		expect(scoreInputs({ suppressed_findings: 1 })).toEqual([
			'1 finding in this window was left out by your suppressions or false-positive marks.',
		]);
	});

	it('says nothing about suppressions when none changed the score', () => {
		expect(scoreInputs({ suppressed_findings: 0 })).toEqual([]);
		expect(scoreInputs({})).toEqual([]);
	});

	it('says the baseline is still learning until six earlier hours are recorded', () => {
		const b = baseline({ ready: false, earlier_hours: 2, is_anomalous: false, deviation: 1 });
		expect(scoreInputs({ baseline: b, busier_window_points: 0 })).toEqual([
			"Still learning what's usual: 2 of 6 earlier hours recorded, so no +15 yet.",
		]);
	});

	// NET-239 review: the web repeats the daemon's warm-up, so a change there must reach the sentence
	it("names the daemon's own warm-up hours (_MIN_BASELINE_HOURS)", () => {
		const source = readFileSync(resolve(__dirname, '../../../../daemon/services/alert_intelligence.py'), 'utf-8');
		const hours = source.match(/^_MIN_BASELINE_HOURS = \(?\s*(\d+)/m)?.[1];
		const b = baseline({ ready: false, earlier_hours: 0, is_anomalous: false });
		expect(scoreInputs({ baseline: b, busier_window_points: 0 })[0]).toContain(`0 of ${hours} earlier hours`);
	});

	it('says when a busier window added 15', () => {
		expect(scoreInputs({ baseline: baseline(), busier_window_points: 15 })).toEqual([
			'Busier than usual (2.4× the usual 1.2K events), so +15.',
		]);
	});

	it('says a busier window added nothing once the score was 75 or more', () => {
		expect(scoreInputs({ baseline: baseline(), busier_window_points: 0 })).toEqual([
			'Busier than usual (2.4×), but the score was already 75 or more, so no +15.',
		]);
	});

	it('says when the window was not busier than usual', () => {
		const b = baseline({ is_anomalous: false, deviation: 1.1 });
		expect(scoreInputs({ baseline: b, busier_window_points: 0 })).toEqual([
			'Not busier than usual (1.1× the usual 1.2K events), so no +15.',
		]);
	});

	it('says nothing about the baseline for a device view or a failed update', () => {
		expect(scoreInputs({ baseline: null, busier_window_points: 0, suppressed_findings: 0 })).toEqual([]);
	});

	it('says nothing about the baseline when the reply lacks any of its new fields', () => {
		expect(scoreInputs({ baseline: baseline({ ready: undefined }), busier_window_points: 15 })).toEqual([]);
		expect(scoreInputs({ baseline: baseline({ earlier_hours: undefined }), busier_window_points: 15 })).toEqual([]);
		expect(scoreInputs({ baseline: baseline() })).toEqual([]);
	});

	it("guesses nothing from an older daemon's reply whose score already includes the +15", () => {
		const older = {
			threat_score: 89,
			baseline: { deviation: 3, avg_events: 10, avg_threat_score: 5, history_points: 9, is_anomalous: true },
		};
		expect(scoreInputs(older)).toEqual([]);
	});

	it('gives the suppressed sentence first, then the baseline one', () => {
		expect(scoreInputs({ suppressed_findings: 2, baseline: baseline(), busier_window_points: 15 })).toEqual([
			`2 ${SUPPRESSED}`,
			'Busier than usual (2.4× the usual 1.2K events), so +15.',
		]);
	});
});
