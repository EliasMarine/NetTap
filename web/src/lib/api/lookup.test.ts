import { describe, it, expect, vi, afterEach } from 'vitest';
import { getWhois, getDnsReverse } from './lookup';

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

function mockFetchNetworkError(): void {
	vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('lookup API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getWhois ------------------------------------------------------------

	describe('getWhois', () => {
		it('calls correct endpoint with encoded IP', async () => {
			const body = { ip: '8.8.8.8', raw: 'NetRange: 8.8.8.0', parsed: { NetRange: '8.8.8.0' }, error: null };
			mockFetchSuccess(body);

			const result = await getWhois('8.8.8.8');
			expect(fetch).toHaveBeenCalledWith('/api/lookup/whois/8.8.8.8');
			expect(result).toEqual(body);
		});

		it('encodes special characters in IP', async () => {
			const body = { ip: '::1', raw: '', parsed: {}, error: null };
			mockFetchSuccess(body);

			await getWhois('::1');
			expect(fetch).toHaveBeenCalledWith('/api/lookup/whois/%3A%3A1');
		});

		it('returns error object on HTTP failure', async () => {
			mockFetchFailure(404);

			const result = await getWhois('10.0.0.1');
			expect(result).toEqual({
				ip: '10.0.0.1',
				raw: '',
				parsed: {},
				error: 'HTTP 404',
			});
		});

		it('returns error object on network failure', async () => {
			mockFetchNetworkError();

			const result = await getWhois('10.0.0.1');
			expect(result).toEqual({
				ip: '10.0.0.1',
				raw: '',
				parsed: {},
				error: 'Network error',
			});
		});
	});

	// -- getDnsReverse -------------------------------------------------------

	describe('getDnsReverse', () => {
		it('calls correct endpoint with encoded IP', async () => {
			const body = { ip: '8.8.8.8', hostname: 'dns.google', aliases: [], addresses: ['8.8.8.8'], error: null };
			mockFetchSuccess(body);

			const result = await getDnsReverse('8.8.8.8');
			expect(fetch).toHaveBeenCalledWith('/api/lookup/dns/8.8.8.8');
			expect(result).toEqual(body);
		});

		it('returns error object on HTTP failure', async () => {
			mockFetchFailure(500);

			const result = await getDnsReverse('192.168.1.1');
			expect(result).toEqual({
				ip: '192.168.1.1',
				hostname: null,
				aliases: [],
				addresses: [],
				error: 'HTTP 500',
			});
		});

		it('returns error object on network failure', async () => {
			mockFetchNetworkError();

			const result = await getDnsReverse('192.168.1.1');
			expect(result).toEqual({
				ip: '192.168.1.1',
				hostname: null,
				aliases: [],
				addresses: [],
				error: 'Network error',
			});
		});
	});
});
