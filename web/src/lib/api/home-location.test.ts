import { describe, it, expect, vi, afterEach } from 'vitest';
import { getHomeLocation, saveHomeLocation, clearHomeLocation, lookupWanLocation, checkHomeLocation } from './home-location';

function reply(status: number, body: unknown) {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: status < 300, status, json: () => Promise.resolve(body) }));
}

const calls = () => vi.mocked(fetch).mock.calls.map(([url, init]) => [url, init?.method ?? 'GET', init?.body ?? null]);

afterEach(() => vi.unstubAllGlobals());

describe('home location client', () => {
	const LONDON = { lat: 51.5074, lon: -0.1278, label: 'London' };

	it('reads the saved location, or null when none is set', async () => {
		reply(200, { home: LONDON });
		expect(await getHomeLocation()).toEqual(LONDON);
		reply(200, { home: null });
		expect(await getHomeLocation()).toBeNull();
	});

	it('saves with PUT and returns what the daemon stored', async () => {
		reply(200, { home: LONDON });
		expect(await saveHomeLocation(LONDON)).toEqual(LONDON);
		expect(calls()).toEqual([['/api/settings/home-location', 'PUT', JSON.stringify(LONDON)]]);
	});

	it('clears with DELETE', async () => {
		reply(200, { home: null });
		await clearHomeLocation();
		expect(calls()).toEqual([['/api/settings/home-location', 'DELETE', null]]);
	});

	it('asks for the WAN suggestion with POST and saves nothing', async () => {
		reply(200, { suggestion: LONDON });
		expect(await lookupWanLocation()).toEqual(LONDON);
		expect(calls()).toEqual([['/api/settings/home-location/wan-lookup', 'POST', null]]);
	});

	it('refuses a 200 reply with no usable location, rather than draw a blank globe', async () => {
		reply(200, {});
		await expect(lookupWanLocation()).rejects.toThrow('no usable location');
		reply(200, { home: { lat: 'north', lon: 0, label: '' } });
		await expect(getHomeLocation()).rejects.toThrow('no usable location');
		await expect(saveHomeLocation(LONDON)).rejects.toThrow('no usable location');
	});

	it("throws the daemon's message, else one with the status", async () => {
		reply(400, { error: "'lat' must be between -90 and 90" });
		await expect(saveHomeLocation(LONDON)).rejects.toThrow("'lat' must be between -90 and 90");
		reply(502, { error: "Couldn't look up your WAN location. Enter the coordinates by hand." });
		await expect(lookupWanLocation()).rejects.toThrow('Enter the coordinates by hand');
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503, json: () => Promise.reject(new Error('not JSON')) }));
		await expect(getHomeLocation()).rejects.toThrow('HTTP 503');
		await expect(clearHomeLocation()).rejects.toThrow('HTTP 503');
	});
});

describe('checkHomeLocation', () => {
	it('turns the form into a location', () => {
		expect(checkHomeLocation({ label: ' Home ', lat: ' 51.5 ', lon: '-0.13' })).toEqual({ lat: 51.5, lon: -0.13, label: 'Home' });
		expect(checkHomeLocation({ label: '', lat: '-90', lon: '180' })).toEqual({ lat: -90, lon: 180, label: '' });
	});

	it.each([
		[{ label: '', lat: '', lon: '0' }, /Latitude/],
		[{ label: '', lat: '91', lon: '0' }, /Latitude/],
		[{ label: '', lat: 'north', lon: '0' }, /Latitude/],
		[{ label: '', lat: '0', lon: '' }, /Longitude/],
		[{ label: '', lat: '0', lon: '-180.5' }, /Longitude/],
		[{ label: '', lat: '0', lon: 'Infinity' }, /Longitude/],
		[{ label: 'x'.repeat(81), lat: '0', lon: '0' }, /at most 80/],
	])('says what is wrong with %j', (form, message) => {
		expect(checkHomeLocation(form)).toMatch(message);
	});
});
