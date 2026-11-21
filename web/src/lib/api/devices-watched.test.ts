import { describe, it, expect, vi, afterEach } from 'vitest';
import { getWatchedDevices, isWatchMinutes, setWatch, watchLabel, type WatchedDevicesResponse } from './devices-watched';

const REPLY: WatchedDevicesResponse = {
	check: { attempt_at: '2026-11-20T10:00:00Z', success_at: '2026-11-20T10:00:00Z', capture_at: '2026-11-20T09:59:30Z', coverage_since: '2026-11-20T08:00:00Z', skipped: null, error: null },
	devices: [{ mac: 'aa:bb:cc:dd:ee:ff', name: 'NAS', after_min: 60, state: 'up', seen_at: '2026-11-20T09:58:00Z', since: '2026-11-20T08:05:00Z' }],
};

function stubFetch(reply: { ok: boolean; status: number; body?: unknown } | Error) {
	const fn = vi.fn(async () => {
		if (reply instanceof Error) throw reply;
		return { ok: reply.ok, status: reply.status, json: async () => reply.body };
	});
	vi.stubGlobal('fetch', fn);
	return fn;
}

describe('watched devices API (NET-331)', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('reads the watched list', async () => {
		const fn = stubFetch({ ok: true, status: 200, body: REPLY });
		await expect(getWatchedDevices()).resolves.toEqual(REPLY);
		expect(fn).toHaveBeenCalledWith('/api/devices/watched');
	});

	// OLD CODE: it('throws on a failed read, never an empty list', …) expected 'Watched devices failed: HTTP 503' (review M4: the daemon's reason)
	it("throws the daemon's own reason on a failed read, never an empty list", async () => {
		stubFetch({ ok: false, status: 503, body: { error: "Watched devices can't be listed: the device details file is unreadable." } });
		await expect(getWatchedDevices()).rejects.toThrow("Watched devices can't be listed: the device details file is unreadable.");
	});

	it('names the status when the reply has no reason, and says when NetTap is out of reach', async () => {
		stubFetch({ ok: false, status: 502, body: 'not json' });
		await expect(getWatchedDevices()).rejects.toThrow('NetTap answered HTTP 502.');
		stubFetch(new TypeError('Failed to fetch'));
		await expect(getWatchedDevices()).rejects.toThrow("Couldn't reach NetTap. Check the connection and try again.");
	});

	it('takes only the five watch times as a current value', () => {
		expect([15, 30, 60, 240, 1440].every(isWatchMinutes)).toBe(true);
		for (const odd of [null, undefined, 0, 45, '60', 60.5]) expect(isWatchMinutes(odd)).toBe(false);
	});

	it('saves a watch with only watch_after_min, to the details route', async () => {
		const device = { mac: 'AA:BB:CC:DD:EE:FF', watch_after_min: 240 };
		const fn = stubFetch({ ok: true, status: 200, body: { device } });
		await expect(setWatch('AA:BB:CC:DD:EE:FF', 240)).resolves.toEqual(device);
		expect(fn).toHaveBeenCalledWith('/api/devices/registry/AA%3ABB%3ACC%3ADD%3AEE%3AFF/details', {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: '{"watch_after_min":240}',
		});
	});

	it('stops watching with exactly {"watch_after_min": null}', async () => {
		const fn = stubFetch({ ok: true, status: 200, body: { device: { mac: 'AA:BB:CC:DD:EE:FF', watch_after_min: null } } });
		await setWatch('AA:BB:CC:DD:EE:FF', null);
		expect(fn.mock.calls[0]).toEqual([expect.any(String), expect.objectContaining({ body: '{"watch_after_min":null}' })]);
	});

	it("passes the daemon's reason on a refused save, and a plain one when NetTap can't be reached", async () => {
		stubFetch({ ok: false, status: 400, body: { error: 'Pick 15, 30, 60, 240 or 1440 minutes.' } });
		await expect(setWatch('AA:BB:CC:DD:EE:FF', 15)).rejects.toThrow('Pick 15, 30, 60, 240 or 1440 minutes.');
		stubFetch(new TypeError('Failed to fetch'));
		await expect(setWatch('AA:BB:CC:DD:EE:FF', 15)).rejects.toThrow("Couldn't reach NetTap. Check the connection and try again.");
	});

	it('names every watch time in words', () => {
		expect([15, 30, 60, 240, 1440].map(watchLabel)).toEqual(['15 minutes', '30 minutes', '1 hour', '4 hours', '1 day']);
	});
});
