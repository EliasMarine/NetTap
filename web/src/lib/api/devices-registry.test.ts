import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getRegistryDevices,
	getRegistryDevice,
	getDeviceTraffic,
	acknowledgeDevice,
} from './devices-registry';

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

function mockFetchReject(): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockRejectedValue(new Error('network error')),
	);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('devices-registry API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getRegistryDevices ---------------------------------------------------

	describe('getRegistryDevices', () => {
		it('returns parsed device list on success', async () => {
			const expected = {
				devices: [
					{
						mac: 'AA:BB:CC:DD:EE:FF',
						ips: ['192.168.1.100'],
						hostnames: ['laptop.local'],
						manufacturer: 'Apple',
						friendly_name: 'My Laptop',
						display_name: 'My Laptop',
						category: 'computer',
						first_seen: '2026-03-01T00:00:00Z',
						last_seen: '2026-03-08T12:00:00Z',
						is_new: false,
						total_bytes: 1500000,
						connection_count: 500,
					},
				],
				total: 1,
			};
			mockFetchSuccess(expected);

			const result = await getRegistryDevices();

			expect(result.devices).toHaveLength(1);
			expect(result.devices[0].mac).toBe('AA:BB:CC:DD:EE:FF');
			expect(result.devices[0].category).toBe('computer');
			expect(result.total).toBe(1);
		});

		it('returns empty array on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getRegistryDevices();

			expect(result.devices).toEqual([]);
			expect(result.total).toBe(0);
		});

		it('returns empty array on network error', async () => {
			mockFetchReject();

			const result = await getRegistryDevices();

			expect(result.devices).toEqual([]);
			expect(result.total).toBe(0);
		});

		it('passes limit and offset parameters', async () => {
			mockFetchSuccess({ devices: [], total: 0 });

			await getRegistryDevices({ limit: 50, offset: 10 });

			const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('limit=50');
			expect(url).toContain('offset=10');
		});
	});

	// -- getRegistryDevice ----------------------------------------------------

	describe('getRegistryDevice', () => {
		it('returns parsed device on success', async () => {
			const expected = {
				mac: 'AA:BB:CC:DD:EE:FF',
				ips: ['192.168.1.100'],
				hostnames: [],
				manufacturer: 'Apple',
				friendly_name: null,
				display_name: 'Apple AA:BB',
				category: 'computer',
				first_seen: '2026-03-01T00:00:00Z',
				last_seen: '2026-03-08T12:00:00Z',
				is_new: false,
			};
			mockFetchSuccess(expected);

			const result = await getRegistryDevice('AA:BB:CC:DD:EE:FF');

			expect(result).not.toBeNull();
			expect(result!.mac).toBe('AA:BB:CC:DD:EE:FF');
		});

		it('returns null on HTTP error', async () => {
			mockFetchFailure(404);

			const result = await getRegistryDevice('AA:BB:CC:DD:EE:FF');

			expect(result).toBeNull();
		});

		it('returns null on network error', async () => {
			mockFetchReject();

			const result = await getRegistryDevice('AA:BB:CC:DD:EE:FF');

			expect(result).toBeNull();
		});

		it('encodes MAC address in URL', async () => {
			mockFetchSuccess({
				mac: 'AA:BB:CC:DD:EE:FF',
				ips: [],
				hostnames: [],
				manufacturer: null,
				friendly_name: null,
				display_name: '',
				category: 'unknown',
				first_seen: '',
				last_seen: '',
				is_new: false,
			});

			await getRegistryDevice('AA:BB:CC:DD:EE:FF');

			const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('AA%3ABB%3ACC%3ADD%3AEE%3AFF');
		});
	});

	// -- getDeviceTraffic -----------------------------------------------------

	describe('getDeviceTraffic', () => {
		it('returns parsed traffic on success', async () => {
			const expected = {
				mac: 'AA:BB:CC:DD:EE:FF',
				total_bytes: 5000000,
				inbound_bytes: 3000000,
				outbound_bytes: 2000000,
				connection_count: 1000,
				top_destinations: [{ ip: '8.8.8.8', bytes: 50000, connections: 30 }],
				top_protocols: [{ name: 'tcp', count: 800 }],
				dns_queries: [{ domain: 'google.com', count: 100 }],
				alerts: [],
				bandwidth_series: [{ timestamp: '2026-03-08T00:00:00Z', bytes: 10000 }],
			};
			mockFetchSuccess(expected);

			const result = await getDeviceTraffic('AA:BB:CC:DD:EE:FF');

			expect(result).not.toBeNull();
			expect(result!.total_bytes).toBe(5000000);
			expect(result!.top_destinations).toHaveLength(1);
			expect(result!.dns_queries).toHaveLength(1);
		});

		it('returns null on HTTP error', async () => {
			mockFetchFailure(404);

			const result = await getDeviceTraffic('AA:BB:CC:DD:EE:FF');

			expect(result).toBeNull();
		});

		it('returns null on network error', async () => {
			mockFetchReject();

			const result = await getDeviceTraffic('AA:BB:CC:DD:EE:FF');

			expect(result).toBeNull();
		});
	});

	// -- acknowledgeDevice ----------------------------------------------------

	describe('acknowledgeDevice', () => {
		it('returns true on success', async () => {
			vi.stubGlobal(
				'fetch',
				vi.fn().mockResolvedValue({ ok: true, status: 200 }),
			);

			const result = await acknowledgeDevice('AA:BB:CC:DD:EE:FF');

			expect(result).toBe(true);
			expect(fetch).toHaveBeenCalledWith(
				expect.stringContaining('AA%3ABB%3ACC%3ADD%3AEE%3AFF'),
				expect.objectContaining({
					method: 'PATCH',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ is_new: false }),
				}),
			);
		});

		it('returns false on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await acknowledgeDevice('AA:BB:CC:DD:EE:FF');

			expect(result).toBe(false);
		});

		it('returns false on network error', async () => {
			mockFetchReject();

			const result = await acknowledgeDevice('AA:BB:CC:DD:EE:FF');

			expect(result).toBe(false);
		});
	});
});
