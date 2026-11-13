import { describe, it, expect, vi, afterEach } from 'vitest';
import { getMomentDevices } from './moment';
import { MOMENT_DEVICES, MOMENT_DEVICES_EMPTY } from '../../../e2e/visual/fixtures/moment';

// NET-249: the moment page's device breakdown, mocked here; the daemon half has its own tests
const reply = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });

describe('getMomentDevices', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('asks for the window and the limit, 10 by default', async () => {
		const fetchMock = vi.fn(async () => reply(200, MOMENT_DEVICES));
		vi.stubGlobal('fetch', fetchMock);
		await expect(getMomentDevices({ from: '2026-11-12T14:05:00.000Z', to: '2026-11-12T14:09:59.999Z' })).resolves.toEqual(MOMENT_DEVICES);
		const url = new URL(String((fetchMock.mock.calls[0] as unknown[])[0]), 'http://x');
		expect(url.pathname).toBe('/api/moment/devices');
		expect(Object.fromEntries(url.searchParams)).toEqual({ from: '2026-11-12T14:05:00.000Z', to: '2026-11-12T14:09:59.999Z', limit: '10' });
		await getMomentDevices({ from: 'a', to: 'b', limit: 25 });
		expect(new URL(String((fetchMock.mock.calls[1] as unknown[])[0]), 'http://x').searchParams.get('limit')).toBe('25');
	});

	it('takes an empty window as no devices', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, MOMENT_DEVICES_EMPTY)));
		await expect(getMomentDevices({ from: 'a', to: 'b' })).resolves.toEqual(MOMENT_DEVICES_EMPTY);
	});

	it.each([
		[503, { error: 'Two other look-ups are being worked out right now; try again in a minute.' }, 'Two other look-ups are being worked out right now; try again in a minute.'],
		[503, { error: 'Working this out took too long. Try a shorter time range.' }, 'Working this out took too long. Try a shorter time range.'],
		[502, { error: 'The device search was incomplete' }, 'The device search was incomplete'],
		[500, {}, 'Moment devices failed: HTTP 500'],
	])("throws the daemon's reason on HTTP %s", async (status, body, message) => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(status, body)));
		await expect(getMomentDevices({ from: 'a', to: 'b' })).rejects.toThrow(message);
	});

	const first = MOMENT_DEVICES.devices[0];
	it.each([
		['no devices list', { ...MOMENT_DEVICES, devices: undefined }],
		['no total_devices', { ...MOMENT_DEVICES, total_devices: undefined }],
		['a device without its bytes', { ...MOMENT_DEVICES, devices: [{ ...first, total_bytes: undefined }] }],
		['an unknown IPv6 reason', { ...MOMENT_DEVICES, devices: [{ ...first, ipv6_left_out_reason: 'other' }] }],
		['a destination without bytes', { ...MOMENT_DEVICES, devices: [{ ...first, destinations: [{ ip: '198.51.100.10', connections: 1 }] }] }],
		['domains missing', { ...MOMENT_DEVICES, devices: [{ ...first, domains: undefined }] }],
	])('throws on a malformed reply (%s) instead of showing a blank', async (_, body) => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, body)));
		await expect(getMomentDevices({ from: 'a', to: 'b' })).rejects.toThrow('malformed');
	});

	it('takes a device with no name or MAC', async () => {
		const body = { ...MOMENT_DEVICES, devices: [{ ...first, name: null, mac: null }] };
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, body)));
		await expect(getMomentDevices({ from: 'a', to: 'b' })).resolves.toEqual(body);
	});
});
