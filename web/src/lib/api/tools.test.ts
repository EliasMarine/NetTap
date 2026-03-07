import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	dnsRecon,
	macLookup,
	ping,
	traceroute,
	sslCertInspect,
	type DnsReconResult,
	type MacLookupResult,
	type PingResult,
	type TracerouteResult,
	type SslCertResult,
} from './tools';

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

function mockFetchFailure(status = 500, body?: unknown): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => (body !== undefined ? Promise.resolve(body) : Promise.reject(new Error('no body'))),
		}),
	);
}

function mockFetchNetworkError(): void {
	vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('tools API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- dnsRecon ------------------------------------------------------------

	describe('dnsRecon', () => {
		it('sends correct POST body and returns parsed response', async () => {
			const expected: DnsReconResult = {
				domain: 'example.com',
				records: {
					A: [{ name: 'example.com', ttl: 300, class: 'IN', type: 'A', value: '93.184.216.34' }],
				},
				total_records: 1,
				record_types_queried: ['A'],
				errors: [],
			};
			mockFetchSuccess(expected);

			const result = await dnsRecon('example.com', ['A']);

			expect(fetch).toHaveBeenCalledOnce();
			expect(fetch).toHaveBeenCalledWith('/api/tools/dns-recon', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ domain: 'example.com', record_types: ['A'] }),
			});
			expect(result).toEqual(expected);
		});

		it('omits record_types when not provided', async () => {
			mockFetchSuccess({ domain: 'example.com', records: {}, total_records: 0, record_types_queried: [], errors: [] });

			await dnsRecon('example.com');

			expect(fetch).toHaveBeenCalledWith('/api/tools/dns-recon', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ domain: 'example.com' }),
			});
		});

		it('returns error defaults on HTTP failure with JSON body', async () => {
			mockFetchFailure(400, { error: 'Invalid domain' });

			const result = await dnsRecon('bad..domain');

			expect(result.records).toEqual({});
			expect(result.total_records).toBe(0);
			expect(result.errors).toEqual(['Invalid domain']);
		});

		it('returns fallback error when response body is not JSON', async () => {
			mockFetchFailure(502);

			const result = await dnsRecon('example.com');

			expect(result.errors).toEqual(['DNS recon failed (HTTP 502)']);
		});

		it('throws on network failure', async () => {
			mockFetchNetworkError();

			await expect(dnsRecon('example.com')).rejects.toThrow('Failed to fetch');
		});
	});

	// -- macLookup -----------------------------------------------------------

	describe('macLookup', () => {
		it('sends correct GET request and returns parsed response', async () => {
			const expected: MacLookupResult = {
				mac: 'AA:BB:CC:DD:EE:FF',
				oui_prefix: 'AA:BB:CC',
				vendor: 'Test Corp',
				found: true,
			};
			mockFetchSuccess(expected);

			const result = await macLookup('AA:BB:CC:DD:EE:FF');

			expect(fetch).toHaveBeenCalledOnce();
			expect(fetch).toHaveBeenCalledWith('/api/tools/mac-lookup/AA%3ABB%3ACC%3ADD%3AEE%3AFF');
			expect(result).toEqual(expected);
		});

		it('returns not-found defaults on HTTP error', async () => {
			mockFetchFailure(404);

			const result = await macLookup('00:00:00:00:00:00');

			expect(result.found).toBe(false);
			expect(result.vendor).toBe('');
		});

		it('throws on network failure', async () => {
			mockFetchNetworkError();

			await expect(macLookup('AA:BB:CC:DD:EE:FF')).rejects.toThrow('Failed to fetch');
		});
	});

	// -- ping ----------------------------------------------------------------

	describe('ping', () => {
		it('sends correct POST body with count and returns parsed response', async () => {
			const expected: PingResult = {
				target: '8.8.8.8',
				raw: 'PING 8.8.8.8 ...',
				packets_sent: 4,
				packets_received: 4,
				packet_loss_pct: 0,
				rtt_min: 1.0,
				rtt_avg: 2.0,
				rtt_max: 3.0,
				rtt_mdev: 0.5,
				replies: [{ bytes: 64, from: '8.8.8.8', seq: 1, ttl: 64, time_ms: 2.0 }],
			};
			mockFetchSuccess(expected);

			const result = await ping('8.8.8.8', 4);

			expect(fetch).toHaveBeenCalledOnce();
			expect(fetch).toHaveBeenCalledWith('/api/tools/ping', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ target: '8.8.8.8', count: 4 }),
			});
			expect(result).toEqual(expected);
		});

		it('omits count when not provided', async () => {
			mockFetchSuccess({ target: '1.1.1.1', raw: '', packets_sent: 0, packets_received: 0, packet_loss_pct: 100, rtt_min: 0, rtt_avg: 0, rtt_max: 0, rtt_mdev: 0, replies: [] });

			await ping('1.1.1.1');

			expect(fetch).toHaveBeenCalledWith('/api/tools/ping', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ target: '1.1.1.1' }),
			});
		});

		it('returns error defaults on HTTP failure', async () => {
			mockFetchFailure(500, { error: 'Host unreachable' });

			const result = await ping('10.0.0.1');

			expect(result.packets_sent).toBe(0);
			expect(result.packet_loss_pct).toBe(100);
			expect(result.error).toBe('Host unreachable');
		});

		it('returns fallback error when response body is not JSON', async () => {
			mockFetchFailure(502);

			const result = await ping('10.0.0.1');

			expect(result.error).toBe('Ping failed (HTTP 502)');
		});

		it('throws on network failure', async () => {
			mockFetchNetworkError();

			await expect(ping('8.8.8.8')).rejects.toThrow('Failed to fetch');
		});
	});

	// -- traceroute ----------------------------------------------------------

	describe('traceroute', () => {
		it('sends correct POST body with maxHops and returns parsed response', async () => {
			const expected: TracerouteResult = {
				target: '8.8.8.8',
				hops: [{ hop: 1, host: 'gateway', ip: '192.168.1.1', rtts: [1.2, 1.3, 1.4] }],
				total_hops: 1,
				raw: 'traceroute to 8.8.8.8 ...',
			};
			mockFetchSuccess(expected);

			const result = await traceroute('8.8.8.8', 15);

			expect(fetch).toHaveBeenCalledOnce();
			expect(fetch).toHaveBeenCalledWith('/api/tools/traceroute', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ target: '8.8.8.8', max_hops: 15 }),
			});
			expect(result).toEqual(expected);
		});

		it('omits max_hops when not provided', async () => {
			mockFetchSuccess({ target: '1.1.1.1', hops: [], total_hops: 0, raw: '' });

			await traceroute('1.1.1.1');

			expect(fetch).toHaveBeenCalledWith('/api/tools/traceroute', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ target: '1.1.1.1' }),
			});
		});

		it('returns error defaults on HTTP failure', async () => {
			mockFetchFailure(500, { error: 'Timeout' });

			const result = await traceroute('10.0.0.1');

			expect(result.hops).toEqual([]);
			expect(result.total_hops).toBe(0);
			expect(result.error).toBe('Timeout');
		});

		it('returns fallback error when response body is not JSON', async () => {
			mockFetchFailure(502);

			const result = await traceroute('10.0.0.1');

			expect(result.error).toBe('Traceroute failed (HTTP 502)');
		});

		it('throws on network failure', async () => {
			mockFetchNetworkError();

			await expect(traceroute('8.8.8.8')).rejects.toThrow('Failed to fetch');
		});
	});

	// -- sslCertInspect ------------------------------------------------------

	describe('sslCertInspect', () => {
		it('sends correct POST body with port and returns parsed response', async () => {
			const expected: SslCertResult = {
				host: 'example.com',
				port: 8443,
				subject: { CN: 'example.com' },
				issuer: { O: 'Test CA' },
				not_before: '2024-01-01T00:00:00Z',
				not_after: '2025-01-01T00:00:00Z',
				serial: 'ABCDEF',
				fingerprint_sha256: 'AA:BB:CC',
				san: ['example.com', '*.example.com'],
				chain: ['example.com', 'Test CA'],
				raw: 'Certificate: ...',
			};
			mockFetchSuccess(expected);

			const result = await sslCertInspect('example.com', 8443);

			expect(fetch).toHaveBeenCalledOnce();
			expect(fetch).toHaveBeenCalledWith('/api/tools/ssl-cert', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ host: 'example.com', port: 8443 }),
			});
			expect(result).toEqual(expected);
		});

		it('omits port when not provided', async () => {
			mockFetchSuccess({ host: 'example.com', port: 443, subject: {}, issuer: {}, not_before: '', not_after: '', serial: '', fingerprint_sha256: '', san: [], chain: [], raw: '' });

			await sslCertInspect('example.com');

			expect(fetch).toHaveBeenCalledWith('/api/tools/ssl-cert', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ host: 'example.com' }),
			});
		});

		it('returns error defaults on HTTP failure', async () => {
			mockFetchFailure(500, { error: 'Connection refused' });

			const result = await sslCertInspect('bad-host.local');

			expect(result.subject).toEqual({});
			expect(result.san).toEqual([]);
			expect(result.error).toBe('Connection refused');
		});

		it('returns fallback error when response body is not JSON', async () => {
			mockFetchFailure(502);

			const result = await sslCertInspect('example.com');

			expect(result.error).toBe('SSL cert inspection failed (HTTP 502)');
		});

		it('defaults port to 443 on error', async () => {
			mockFetchFailure(500, { error: 'fail' });

			const result = await sslCertInspect('example.com');

			expect(result.port).toBe(443);
		});

		it('throws on network failure', async () => {
			mockFetchNetworkError();

			await expect(sslCertInspect('example.com')).rejects.toThrow('Failed to fetch');
		});
	});
});
