import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getDevices,
	getDeviceDetail,
	getDeviceConnections,
} from './devices';

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

describe('devices API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getDevices -----------------------------------------------------------

	describe('getDevices', () => {
		it('returns parsed device list on success', async () => {
			const expected = {
				from: '2026-02-25T00:00:00Z',
				to: '2026-02-26T00:00:00Z',
				limit: 100,
				devices: [
					{
						ip: '192.168.1.100',
						mac: 'AA:BB:CC:DD:EE:FF',
						hostname: 'my-laptop.local',
						manufacturer: 'Apple',
						os_hint: 'macOS',
						first_seen: '2026-02-25T00:00:00Z',
						last_seen: '2026-02-25T23:59:59Z',
						total_bytes: 1500000,
						connection_count: 500,
						protocols: ['tcp', 'udp'],
						alert_count: 2,
					},
				],
			};
			mockFetchSuccess(expected);

			const result = await getDevices();

			expect(fetch).toHaveBeenCalledWith('/api/devices');
			expect(result.devices).toHaveLength(1);
			expect(result.devices[0].ip).toBe('192.168.1.100');
			expect(result.devices[0].manufacturer).toBe('Apple');
		});

		it('returns empty devices array on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getDevices();

			expect(result.devices).toEqual([]);
			expect(result.limit).toBe(100);
		});

		it('passes sort, order, and limit parameters', async () => {
			mockFetchSuccess({ from: '', to: '', limit: 50, devices: [] });

			await getDevices({ sort: 'bytes', order: 'asc', limit: 50 });

			expect(fetch).toHaveBeenCalledWith(
				expect.stringContaining('/api/devices?')
			);
			const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('sort=bytes');
			expect(url).toContain('order=asc');
			expect(url).toContain('limit=50');
		});

		it('passes time range parameters', async () => {
			mockFetchSuccess({ from: '', to: '', limit: 100, devices: [] });

			await getDevices({ from: '2026-02-25T00:00:00Z', to: '2026-02-26T00:00:00Z' });

			const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('from=');
			expect(url).toContain('to=');
		});
	});

	// -- getDeviceDetail ------------------------------------------------------

	describe('getDeviceDetail', () => {
		it('returns parsed device detail on success', async () => {
			const expected = {
				device: {
					ip: '192.168.1.100',
					mac: '00:03:93:11:22:33',
					hostname: 'iphone.local',
					manufacturer: 'Apple',
					os_hint: 'iOS',
					first_seen: '2026-02-25T00:00:00Z',
					last_seen: '2026-02-25T23:59:59Z',
					total_bytes: 800000,
					connection_count: 200,
					protocols: ['tcp'],
					alert_count: 1,
					top_destinations: [
						{ ip: '8.8.8.8', bytes: 50000, connections: 30 },
					],
					dns_queries: [
						{ domain: 'apple.com', count: 25 },
					],
					bandwidth_series: [
						{ timestamp: '2026-02-25T00:00:00Z', bytes: 10000 },
					],
				},
			};
			mockFetchSuccess(expected);

			const result = await getDeviceDetail('192.168.1.100');

			expect(fetch).toHaveBeenCalledWith('/api/devices/192.168.1.100');
			expect(result.device.ip).toBe('192.168.1.100');
			expect(result.device.manufacturer).toBe('Apple');
			expect(result.device.top_destinations).toHaveLength(1);
			expect(result.device.dns_queries).toHaveLength(1);
			expect(result.device.bandwidth_series).toHaveLength(1);
		});

		it('returns empty device on HTTP error', async () => {
			mockFetchFailure(502);

			const result = await getDeviceDetail('192.168.1.100');

			expect(result.device.ip).toBe('192.168.1.100');
			expect(result.device.total_bytes).toBe(0);
			expect(result.device.top_destinations).toEqual([]);
			expect(result.device.dns_queries).toEqual([]);
			expect(result.device.bandwidth_series).toEqual([]);
		});

		it('passes time range parameters', async () => {
			mockFetchSuccess({
				device: {
					ip: '192.168.1.100', mac: null, hostname: null, manufacturer: null,
					os_hint: null, first_seen: '', last_seen: '', total_bytes: 0,
					connection_count: 0, protocols: [], alert_count: 0,
					top_destinations: [], dns_queries: [], bandwidth_series: [],
				},
			});

			await getDeviceDetail('192.168.1.100', {
				from: '2026-02-25T00:00:00Z',
				to: '2026-02-26T00:00:00Z',
			});

			const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('from=');
			expect(url).toContain('to=');
		});

		it('encodes IP address in URL', async () => {
			mockFetchSuccess({
				device: {
					ip: '10.0.0.1', mac: null, hostname: null, manufacturer: null,
					os_hint: null, first_seen: '', last_seen: '', total_bytes: 0,
					connection_count: 0, protocols: [], alert_count: 0,
					top_destinations: [], dns_queries: [], bandwidth_series: [],
				},
			});

			await getDeviceDetail('10.0.0.1');

			expect(fetch).toHaveBeenCalledWith('/api/devices/10.0.0.1');
		});
	});

	// -- getDeviceConnections -------------------------------------------------

	describe('getDeviceConnections', () => {
		it('returns parsed connections on success', async () => {
			const expected = {
				from: '2026-02-25T00:00:00Z',
				to: '2026-02-26T00:00:00Z',
				ip: '192.168.1.100',
				page: 1,
				size: 50,
				total: 150,
				total_pages: 3,
				connections: [
					{
						_id: 'conn1',
						_index: 'zeek-conn-2026.02.25',
						ts: '2026-02-25T12:00:00Z',
						proto: 'tcp',
					},
				],
			};
			mockFetchSuccess(expected);

			const result = await getDeviceConnections('192.168.1.100');

			expect(fetch).toHaveBeenCalledWith('/api/devices/192.168.1.100/connections');
			expect(result.total).toBe(150);
			expect(result.total_pages).toBe(3);
			expect(result.connections).toHaveLength(1);
		});

		it('returns empty connections on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getDeviceConnections('192.168.1.100');

			expect(result.total).toBe(0);
			expect(result.connections).toEqual([]);
			expect(result.ip).toBe('192.168.1.100');
		});

		it('passes page and size parameters', async () => {
			mockFetchSuccess({
				from: '', to: '', ip: '192.168.1.100',
				page: 3, size: 25, total: 0, total_pages: 0, connections: [],
			});

			await getDeviceConnections('192.168.1.100', { page: 3, size: 25 });

			const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('page=3');
			expect(url).toContain('size=25');
		});

		it('passes time range with pagination parameters', async () => {
			mockFetchSuccess({
				from: '', to: '', ip: '192.168.1.100',
				page: 1, size: 50, total: 0, total_pages: 0, connections: [],
			});

			await getDeviceConnections('192.168.1.100', {
				from: '2026-02-25T00:00:00Z',
				to: '2026-02-26T00:00:00Z',
				page: 2,
				size: 100,
			});

			const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('from=');
			expect(url).toContain('to=');
			expect(url).toContain('page=2');
			expect(url).toContain('size=100');
		});
	});
});
