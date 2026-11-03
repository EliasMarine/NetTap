import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getTopDomains,
	getDeviceDns,
	getNxdomains,
	getQueryTypes,
	getDnsTimeline,
	getSuspiciousDns,
	getDnsStats,
} from './dns';

function mockFetchSuccess(body: unknown): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
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

describe('DNS API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	describe('getTopDomains', () => {
		it('returns domains on success', async () => {
			mockFetchSuccess({
				from: '', to: '',
				domains: [{ domain: 'google.com', count: 100, unique_clients: 5 }],
			});

			const result = await getTopDomains();
			expect(result.domains).toHaveLength(1);
			expect(result.domains[0].domain).toBe('google.com');
		});

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(500);
			await expect(getTopDomains()).rejects.toThrow('HTTP 500');
		});

		it('passes limit parameter', async () => {
			mockFetchSuccess({ from: '', to: '', domains: [] });
			await getTopDomains({ limit: 10 });
			const url = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('limit=10');
		});
	});

	describe('getDeviceDns', () => {
		it('returns device domains on success', async () => {
			mockFetchSuccess({
				device_ip: '192.168.1.100',
				from: '', to: '',
				domains: [{ domain: 'api.example.com', count: 50, query_types: [] }],
			});

			const result = await getDeviceDns('192.168.1.100');
			expect(result.domains).toHaveLength(1);
			expect(result.device_ip).toBe('192.168.1.100');
		});

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(500);
			await expect(getDeviceDns('10.0.0.1')).rejects.toThrow('HTTP 500');
		});
	});

	describe('getNxdomains', () => {
		it('returns NXDOMAIN entries', async () => {
			mockFetchSuccess({
				from: '', to: '',
				nxdomains: [{ domain: 'bad.test', count: 10, clients: ['192.168.1.10'] }],
			});

			const result = await getNxdomains();
			expect(result.nxdomains).toHaveLength(1);
		});

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(500);
			await expect(getNxdomains()).rejects.toThrow('HTTP 500');
		});
	});

	describe('getQueryTypes', () => {
		it('returns type distribution', async () => {
			mockFetchSuccess({
				from: '', to: '',
				types: [
					{ type: 'A', count: 1000 },
					{ type: 'AAAA', count: 500 },
				],
			});

			const result = await getQueryTypes();
			expect(result.types).toHaveLength(2);
		});

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(500);
			await expect(getQueryTypes()).rejects.toThrow('HTTP 500');
		});
	});

	describe('getDnsTimeline', () => {
		it('returns timeline series', async () => {
			mockFetchSuccess({
				from: '', to: '', interval: '1m',
				series: [
					{ timestamp: '2026-01-01T00:00:00Z', count: 100 },
					{ timestamp: '2026-01-01T00:01:00Z', count: 150 },
				],
			});

			const result = await getDnsTimeline();
			expect(result.series).toHaveLength(2);
		});

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(500);
			await expect(getDnsTimeline()).rejects.toThrow('HTTP 500');
		});
	});

	describe('getSuspiciousDns', () => {
		it('returns suspicious patterns', async () => {
			mockFetchSuccess({
				from: '', to: '',
				suspicious: [
					{ type: 'long_domain', domain: 'a'.repeat(60) + '.evil.com', count: 5, severity: 'medium', description: 'Long domain' },
				],
			});

			const result = await getSuspiciousDns();
			expect(result.suspicious).toHaveLength(1);
			expect(result.suspicious[0].type).toBe('long_domain');
		});

		// #96: an empty list on failure read as "No suspicious DNS patterns detected"
		it('throws on failure so the page can say the check failed', async () => {
			mockFetchFailure(500);
			await expect(getSuspiciousDns()).rejects.toThrow('HTTP 500');
		});
	});

	describe('getDnsStats', () => {
		it('returns hero stats', async () => {
			mockFetchSuccess({
				total_queries: 10000,
				unique_domains: 500,
				nxdomain_count: 42,
				avg_resolution_ms: 5.0,
			});

			const result = await getDnsStats();
			expect(result.total_queries).toBe(10000);
			expect(result.unique_domains).toBe(500);
		});

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(500);
			await expect(getDnsStats()).rejects.toThrow('HTTP 500');
		});
	});
});
