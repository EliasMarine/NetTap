import { describe, it, expect, vi, afterEach } from 'vitest';
import { lookupGeoIP, lookupGeoIPBatch } from './geoip';

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

describe('geoip API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- lookupGeoIP ---------------------------------------------------------

	describe('lookupGeoIP', () => {
		it('returns parsed GeoIP data on success', async () => {
			const expected = {
				ip: '8.8.8.8',
				country: 'United States',
				country_code: 'US',
				city: 'Mountain View',
				latitude: 37.386,
				longitude: -122.084,
				asn: 15169,
				organization: 'Google LLC',
				is_private: false,
			};
			mockFetchSuccess(expected);

			const result = await lookupGeoIP('8.8.8.8');

			expect(fetch).toHaveBeenCalledWith('/api/geoip/8.8.8.8');
			expect(result).toEqual(expected);
		});

		it('returns private network data for private IP', async () => {
			const expected = {
				ip: '192.168.1.1',
				country: 'Private Network',
				country_code: 'XX',
				city: null,
				latitude: null,
				longitude: null,
				asn: null,
				organization: null,
				is_private: true,
			};
			mockFetchSuccess(expected);

			const result = await lookupGeoIP('192.168.1.1');

			expect(result.is_private).toBe(true);
			expect(result.country).toBe('Private Network');
		});

		it('returns fallback result on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await lookupGeoIP('8.8.8.8');

			expect(result.ip).toBe('8.8.8.8');
			expect(result.country).toBe('Unknown');
			expect(result.country_code).toBe('XX');
			expect(result.is_private).toBe(false);
			expect(result.city).toBeNull();
			expect(result.organization).toBeNull();
		});

		it('URL-encodes the IP address', async () => {
			mockFetchSuccess({
				ip: '::1',
				country: 'Private Network',
				country_code: 'XX',
				city: null,
				latitude: null,
				longitude: null,
				asn: null,
				organization: null,
				is_private: true,
			});

			await lookupGeoIP('::1');

			expect(fetch).toHaveBeenCalledWith('/api/geoip/%3A%3A1');
		});

		it('returns fallback result on 400 error', async () => {
			mockFetchFailure(400);

			const result = await lookupGeoIP('invalid');

			expect(result.country).toBe('Unknown');
			expect(result.ip).toBe('invalid');
		});
	});

	// -- lookupGeoIPBatch ----------------------------------------------------

	describe('lookupGeoIPBatch', () => {
		it('returns parsed batch results on success', async () => {
			const expected = {
				results: [
					{
						ip: '8.8.8.8',
						country: 'United States',
						country_code: 'US',
						city: 'Mountain View',
						latitude: 37.386,
						longitude: -122.084,
						asn: 15169,
						organization: 'Google LLC',
						is_private: false,
					},
					{
						ip: '1.1.1.1',
						country: 'United States',
						country_code: 'US',
						city: 'San Francisco',
						latitude: null,
						longitude: null,
						asn: 13335,
						organization: 'Cloudflare, Inc.',
						is_private: false,
					},
				],
			};
			mockFetchSuccess(expected);

			const result = await lookupGeoIPBatch(['8.8.8.8', '1.1.1.1']);

			expect(fetch).toHaveBeenCalledWith('/api/geoip/batch?ips=8.8.8.8,1.1.1.1');
			expect(result.results).toHaveLength(2);
			expect(result.results[0].ip).toBe('8.8.8.8');
			expect(result.results[1].ip).toBe('1.1.1.1');
		});

		it('returns empty results for empty array', async () => {
			const result = await lookupGeoIPBatch([]);

			// Should NOT call fetch at all
			expect(result.results).toEqual([]);
		});

		it('caps at 50 IPs on the client side', async () => {
			mockFetchSuccess({ results: [] });

			const ips = Array.from({ length: 60 }, (_, i) => `203.0.113.${i}`);
			await lookupGeoIPBatch(ips);

			// Verify the URL only contains 50 IPs
			const callUrl = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			const ipsParam = new URL(callUrl, 'http://localhost').searchParams.get('ips') ?? '';
			const sentIps = ipsParam.split(',');
			expect(sentIps).toHaveLength(50);
		});

		it('returns empty results on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await lookupGeoIPBatch(['8.8.8.8']);

			expect(result.results).toEqual([]);
		});

		it('includes invalid IPs in response when present', async () => {
			const expected = {
				results: [
					{
						ip: '8.8.8.8',
						country: 'United States',
						country_code: 'US',
						city: 'Mountain View',
						latitude: null,
						longitude: null,
						asn: 15169,
						organization: 'Google LLC',
						is_private: false,
					},
				],
				invalid: ['not-an-ip'],
			};
			mockFetchSuccess(expected);

			const result = await lookupGeoIPBatch(['8.8.8.8', 'not-an-ip']);

			expect(result.results).toHaveLength(1);
			expect(result.invalid).toEqual(['not-an-ip']);
		});

		it('URL-encodes IPs with special characters', async () => {
			mockFetchSuccess({ results: [] });

			await lookupGeoIPBatch(['::1', '8.8.8.8']);

			expect(fetch).toHaveBeenCalledWith(
				expect.stringContaining('%3A%3A1')
			);
		});

		it('handles single IP in batch', async () => {
			const expected = {
				results: [
					{
						ip: '9.9.9.9',
						country: 'United States',
						country_code: 'US',
						city: 'Berkeley',
						latitude: null,
						longitude: null,
						asn: 19281,
						organization: 'Quad9',
						is_private: false,
					},
				],
			};
			mockFetchSuccess(expected);

			const result = await lookupGeoIPBatch(['9.9.9.9']);

			expect(result.results).toHaveLength(1);
			expect(result.results[0].organization).toBe('Quad9');
		});
	});
});
