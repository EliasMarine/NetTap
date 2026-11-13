import { describe, it, expect, vi, afterEach } from 'vitest';
import { getDeviceCompare, type DeviceCompareResponse } from './device-compare';

// NET-265: the daemon half has its own tests (daemon/tests/test_device_compare_api.py)
const reply = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });
const QUERY = {
	ip: '192.168.1.30',
	a_from: '2026-11-12T21:00:00.000Z',
	a_to: '2026-11-13T21:00:00.000Z',
	b_from: '2026-11-13T21:00:00.000Z',
	b_to: '2026-11-14T21:00:00.000Z',
};
const period = (from: string, to: string, total_bytes: number, destinations: number | null) => ({
	from,
	to,
	total_bytes,
	destinations,
	list_complete: true,
	buckets_exact: true,
});
const COMPLETE: DeviceCompareResponse = {
	ip: QUERY.ip,
	a: period(QUERY.a_from, QUERY.a_to, 1_200_000_000, 3),
	b: period(QUERY.b_from, QUERY.b_to, 3_400_000_000, 5),
	exact: true,
	complete: true,
	new: { total: 2, items: [{ ip: '192.0.2.81', org: null, bytes: 900 }] },
	gone: { total: 1, items: [{ ip: '198.51.100.7', org: 'AS64500 Example', bytes: 400 }] },
	changed: { total: 1, partial: false, items: [{ ip: '203.0.113.6', org: null, a_bytes: 50, b_bytes: 1050, delta: 1000 }] },
};
const INCOMPLETE: DeviceCompareResponse = {
	...COMPLETE,
	a: { ...COMPLETE.a, list_complete: false },
	complete: false,
	new: null,
	gone: null,
	changed: { ...COMPLETE.changed!, partial: true },
};
const ESTIMATED: DeviceCompareResponse = {
	...COMPLETE,
	a: { ...COMPLETE.a, buckets_exact: false, destinations: null },
	exact: false,
	complete: false,
	new: null,
	gone: null,
	changed: null,
};

describe('getDeviceCompare', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('asks for the device and both periods', async () => {
		const fetchMock = vi.fn(async () => reply(200, COMPLETE));
		vi.stubGlobal('fetch', fetchMock);
		await expect(getDeviceCompare(QUERY)).resolves.toEqual(COMPLETE);
		const url = new URL(String((fetchMock.mock.calls[0] as unknown[])[0]), 'http://x');
		expect(url.pathname).toBe('/api/moment/device-compare');
		expect(Object.fromEntries(url.searchParams)).toEqual(QUERY);
	});

	it.each([
		['a list incomplete', INCOMPLETE],
		['buckets estimated', ESTIMATED],
	])('takes the reply with what it withholds as null (%s)', async (_, body) => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, body)));
		await expect(getDeviceCompare(QUERY)).resolves.toEqual(body);
	});

	it.each([
		[400, { error: "A period can't end in the future." }, "A period can't end in the future."],
		[503, { error: 'Working this out took too long. Try a shorter time range.' }, 'Working this out took too long. Try a shorter time range.'],
		[500, {}, 'Device compare failed: HTTP 500'],
	])("throws the daemon's reason on HTTP %s", async (status, body, message) => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(status, body)));
		await expect(getDeviceCompare(QUERY)).rejects.toThrow(message);
	});

	it.each([
		['no second period', { ...COMPLETE, b: undefined }],
		['a period without its total', { ...COMPLETE, a: { ...COMPLETE.a, total_bytes: undefined } }],
		['a complete reply without its new list', { ...COMPLETE, new: null }],
		['an incomplete reply with a new list', { ...INCOMPLETE, new: COMPLETE.new }],
		['an exact reply without its changes', { ...COMPLETE, changed: null }],
		['changes without partial', { ...COMPLETE, changed: { total: 0, items: [] } }],
		['an estimated reply with changes', { ...ESTIMATED, changed: COMPLETE.changed }],
		['a change without its delta', { ...COMPLETE, changed: { ...COMPLETE.changed!, items: [{ ip: '203.0.113.6', org: null, a_bytes: 1, b_bytes: 2 }] } }],
		['a destination without its organisation', { ...COMPLETE, new: { total: 1, items: [{ ip: '192.0.2.81', bytes: 900 }] } }],
	])('throws on a malformed reply (%s) instead of showing a blank', async (_, body) => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, body)));
		await expect(getDeviceCompare(QUERY)).rejects.toThrow('malformed');
	});
});
