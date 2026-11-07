import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getRegistryDevices,
	getRegistryDevice,
	getDeviceTraffic,
	acknowledgeDevice,
	isNewDevice,
	setDeviceName,
	clearDeviceName,
	setDevicePicture,
	clearDevicePicture,
	DEVICE_ICONS,
} from './devices-registry';

// NET-158: the "New" chip read is_new (cleared on the device's next update), so it rarely
// showed while "New in 24 h" counted first_seen; both use first_seen now
describe('isNewDevice', () => {
	const NOW = Date.parse('2026-11-05T12:00:00Z');

	it('is new when first seen within the last 24 hours, whatever is_new says', () => {
		expect(isNewDevice({ first_seen: '2026-11-05T01:00:00Z' }, NOW)).toBe(true);
		expect(isNewDevice({ first_seen: '2026-11-04T12:00:00Z' }, NOW)).toBe(true); // the count's gte
	});

	it('is not new when first seen earlier, or when first_seen is unreadable', () => {
		expect(isNewDevice({ first_seen: '2026-11-04T11:59:59Z' }, NOW)).toBe(false);
		expect(isNewDevice({ first_seen: '' }, NOW)).toBe(false);
	});
});

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

		// #96: a fake-empty result on failure read as a real "none" or 0
		it('throws on HTTP error so the page can say it failed', async () => {
			mockFetchFailure(502);
			await expect(getRegistryDevices()).rejects.toThrow('HTTP 502');
		});

		it('rejects on network error', async () => {
			mockFetchReject();
			await expect(getRegistryDevices()).rejects.toThrow();
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
			// #89: the daemon wraps the device; the client returned the wrapper and the page crashed
			mockFetchSuccess({ device: expected });

			const result = await getRegistryDevice('AA:BB:CC:DD:EE:FF');

			expect(result).not.toBeNull();
			expect(result!.mac).toBe('AA:BB:CC:DD:EE:FF');
			expect(result!.ips).toEqual(['192.168.1.100']);
		});

		it('returns null when the registry has no such device (404)', async () => {
			mockFetchFailure(404);

			const result = await getRegistryDevice('AA:BB:CC:DD:EE:FF');

			expect(result).toBeNull();
		});

		// #96: every failure read as "Device not found"
		it('throws on any other HTTP error', async () => {
			mockFetchFailure(500);
			await expect(getRegistryDevice('AA:BB:CC:DD:EE:FF')).rejects.toThrow('HTTP 500');
		});

		it('rejects on network error', async () => {
			mockFetchReject();
			await expect(getRegistryDevice('AA:BB:CC:DD:EE:FF')).rejects.toThrow();
		});

		it('encodes MAC address in URL', async () => {
			mockFetchSuccess({
				device: {
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
				},
			});

			await getRegistryDevice('AA:BB:CC:DD:EE:FF');

			const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('AA%3ABB%3ACC%3ADD%3AEE%3AFF');
		});
	});

	// -- getDeviceTraffic -----------------------------------------------------

	describe('getDeviceTraffic', () => {
		it('returns parsed traffic on success', async () => {
			// #89: the daemon's real reply: {from, to, traffic: {...}}, no DNS/alerts/series
			const traffic = {
				mac: 'AA:BB:CC:DD:EE:FF',
				total_bytes: 5000000,
				inbound_bytes: 3000000,
				outbound_bytes: 2000000,
				connection_count: 1000,
				protocols: ['tcp'],
				top_destinations: [{ ip: '8.8.8.8', bytes: 50000, connections: 30 }],
				top_protocols: [{ name: 'tcp', count: 800 }],
			};
			mockFetchSuccess({ from: '', to: '', traffic });

			const result = await getDeviceTraffic('AA:BB:CC:DD:EE:FF');

			expect(result).not.toBeNull();
			expect(result!.total_bytes).toBe(5000000);
			expect(result!.inbound_bytes).toBe(3000000);
			expect(result!.top_destinations).toHaveLength(1);
		});

		it('returns null when the registry has no such device (404)', async () => {
			mockFetchFailure(404);

			const result = await getDeviceTraffic('AA:BB:CC:DD:EE:FF');

			expect(result).toBeNull();
		});

		// #96: every failure read as "Device not found"
		it('throws on any other HTTP error', async () => {
			mockFetchFailure(500);
			await expect(getDeviceTraffic('AA:BB:CC:DD:EE:FF')).rejects.toThrow('HTTP 500');
		});

		it('asks for the window it is given, and for none without one', async () => {
			mockFetchSuccess({ from: '', to: '', traffic: null });
			await getDeviceTraffic('AA:BB', { from: '2026-11-06T00:00:00.000Z', to: '2026-11-07T00:00:00.000Z' });
			await getDeviceTraffic('AA:BB');
			const urls = vi.mocked(fetch).mock.calls.map((c) => String(c[0]));
			expect(urls).toEqual([
				'/api/devices/registry/AA%3ABB/traffic?from=2026-11-06T00%3A00%3A00.000Z&to=2026-11-07T00%3A00%3A00.000Z',
				'/api/devices/registry/AA%3ABB/traffic',
			]);
		});

		it('rejects on network error', async () => {
			mockFetchReject();
			await expect(getDeviceTraffic('AA:BB:CC:DD:EE:FF')).rejects.toThrow();
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

// NET-200: the owner's name and picture
describe('device name and picture saves', () => {
	afterEach(() => vi.unstubAllGlobals());
	const saved = { mac: 'AA:BB:CC:DD:EE:FF', display_name: 'Living room TV', custom_name: 'Living room TV' };

	it('PUTs the name as JSON and resolves to the saved device', async () => {
		mockFetchSuccess({ device: saved });
		await expect(setDeviceName('AA:BB:CC:DD:EE:FF', 'Living room TV')).resolves.toEqual(saved);
		expect(fetch).toHaveBeenCalledWith('/api/devices/registry/AA%3ABB%3ACC%3ADD%3AEE%3AFF/name', {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ name: 'Living room TV' }),
		});
	});

	it('DELETEs the name and the picture with no body', async () => {
		mockFetchSuccess({ device: saved });
		await clearDeviceName('AA:BB:CC:DD:EE:FF');
		expect(fetch).toHaveBeenLastCalledWith('/api/devices/registry/AA%3ABB%3ACC%3ADD%3AEE%3AFF/name', { method: 'DELETE' });
		await clearDevicePicture('AA:BB:CC:DD:EE:FF');
		expect(fetch).toHaveBeenLastCalledWith('/api/devices/registry/AA%3ABB%3ACC%3ADD%3AEE%3AFF/picture', { method: 'DELETE' });
	});

	it('PUTs exactly the icon or the image it is given', async () => {
		mockFetchSuccess({ device: saved });
		await setDevicePicture('AA:BB:CC:DD:EE:FF', { icon: 'tv' });
		expect(vi.mocked(fetch).mock.calls[0][1]).toMatchObject({ method: 'PUT', body: '{"icon":"tv"}' });
		await setDevicePicture('AA:BB:CC:DD:EE:FF', { image: 'data:image/webp;base64,UklGRg==' });
		expect(vi.mocked(fetch).mock.calls[1][1]).toMatchObject({ body: '{"image":"data:image/webp;base64,UklGRg=="}' });
	});

	it("throws the daemon's own reason", async () => {
		mockFetchSuccess({ error: 'Pictures must be PNG, JPEG or WebP' }, 400);
		await expect(setDevicePicture('AA:BB:CC:DD:EE:FF', { image: 'x' })).rejects.toThrow('Pictures must be PNG, JPEG or WebP');
	});

	it('says the picture is too large on a 413 from the server in front', async () => {
		mockFetchFailure(413);
		await expect(setDevicePicture('AA:BB:CC:DD:EE:FF', { image: 'x' })).rejects.toThrow('The picture is too large');
	});

	it('throws on a reply without a device, naming the status', async () => {
		mockFetchFailure(502);
		await expect(setDeviceName('AA:BB:CC:DD:EE:FF', 'x')).rejects.toThrow("Couldn't save the device: HTTP 502");
	});

	it('offers only icons the icon set has', async () => {
		const { ICONS } = await import('$lib/components/ui/icons');
		for (const name of DEVICE_ICONS) expect(Object.hasOwn(ICONS, name)).toBe(true);
	});
});
