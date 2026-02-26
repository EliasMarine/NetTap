import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
	analyzePcap,
	getTSharkStatus,
	getProtocols,
	getFields,
	type TSharkAnalyzeRequest,
	type TSharkAnalyzeResponse,
	type TSharkStatus,
} from './tshark';

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

describe('tshark API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- analyzePcap ---------------------------------------------------------

	describe('analyzePcap', () => {
		it('sends the correct request body and returns parsed response', async () => {
			const expected: TSharkAnalyzeResponse = {
				packets: [{ _source: { layers: {} } }],
				packet_count: 1,
				truncated: false,
				tshark_version: '4.2.0',
			};
			mockFetchSuccess(expected);

			const req: TSharkAnalyzeRequest = {
				pcap_path: '/captures/test.pcap',
				display_filter: 'http',
				max_packets: 100,
				output_format: 'json',
				fields: ['ip.src', 'ip.dst'],
			};

			const result = await analyzePcap(req);

			expect(fetch).toHaveBeenCalledOnce();
			expect(fetch).toHaveBeenCalledWith('/api/tshark/analyze', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(req),
			});
			expect(result).toEqual(expected);
		});

		it('returns sensible defaults on HTTP error with JSON body', async () => {
			mockFetchFailure(400, { error: 'Invalid filter syntax' });

			const result = await analyzePcap({ pcap_path: '/bad.pcap' });

			expect(result.packets).toEqual([]);
			expect(result.packet_count).toBe(0);
			expect(result.truncated).toBe(false);
			expect(result.tshark_version).toBe('');
			expect(result.error).toBe('Invalid filter syntax');
		});

		it('returns fallback error message when response body is not JSON', async () => {
			vi.stubGlobal(
				'fetch',
				vi.fn().mockResolvedValue({
					ok: false,
					status: 502,
					json: () => Promise.reject(new Error('not json')),
				}),
			);

			const result = await analyzePcap({ pcap_path: '/test.pcap' });

			expect(result.error).toBe('Analysis failed (HTTP 502)');
		});

		it('handles network failure gracefully', async () => {
			mockFetchNetworkError();

			await expect(analyzePcap({ pcap_path: '/test.pcap' })).rejects.toThrow('Failed to fetch');
		});
	});

	// -- getTSharkStatus -----------------------------------------------------

	describe('getTSharkStatus', () => {
		it('returns parsed status on success', async () => {
			const expected: TSharkStatus = {
				available: true,
				version: '4.2.0',
				container_running: true,
				container_name: 'nettap-tshark',
			};
			mockFetchSuccess(expected);

			const result = await getTSharkStatus();

			expect(fetch).toHaveBeenCalledWith('/api/tshark/status');
			expect(result).toEqual(expected);
		});

		it('returns offline defaults on HTTP error', async () => {
			mockFetchFailure(503);

			const result = await getTSharkStatus();

			expect(result.available).toBe(false);
			expect(result.version).toBe('');
			expect(result.container_running).toBe(false);
			expect(result.container_name).toBe('');
		});

		it('handles network failure gracefully', async () => {
			mockFetchNetworkError();

			// getTSharkStatus does not catch thrown errors, it re-throws
			await expect(getTSharkStatus()).rejects.toThrow('Failed to fetch');
		});
	});

	// -- getProtocols --------------------------------------------------------

	describe('getProtocols', () => {
		it('returns protocol list on success', async () => {
			const expected = {
				protocols: [
					{ name: 'tcp', description: 'Transmission Control Protocol' },
					{ name: 'udp', description: 'User Datagram Protocol' },
				],
				count: 2,
			};
			mockFetchSuccess(expected);

			const result = await getProtocols();

			expect(fetch).toHaveBeenCalledWith('/api/tshark/protocols');
			expect(result).toEqual(expected);
		});

		it('returns empty list on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getProtocols();

			expect(result.protocols).toEqual([]);
			expect(result.count).toBe(0);
		});
	});

	// -- getFields -----------------------------------------------------------

	describe('getFields', () => {
		it('returns all fields when no protocol is supplied', async () => {
			const expected = {
				fields: [{ name: 'ip.src', description: 'Source IP', type: 'string' }],
				count: 1,
			};
			mockFetchSuccess(expected);

			const result = await getFields();

			expect(fetch).toHaveBeenCalledWith('/api/tshark/fields');
			expect(result).toEqual(expected);
		});

		it('appends protocol query parameter when supplied', async () => {
			mockFetchSuccess({ fields: [], count: 0 });

			await getFields('tcp');

			expect(fetch).toHaveBeenCalledWith('/api/tshark/fields?protocol=tcp');
		});

		it('encodes special characters in the protocol parameter', async () => {
			mockFetchSuccess({ fields: [], count: 0 });

			await getFields('some protocol');

			expect(fetch).toHaveBeenCalledWith('/api/tshark/fields?protocol=some%20protocol');
		});

		it('returns empty list on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getFields('tcp');

			expect(result.fields).toEqual([]);
			expect(result.count).toBe(0);
		});
	});
});
