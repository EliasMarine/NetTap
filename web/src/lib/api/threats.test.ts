import { describe, it, expect, vi, afterEach } from 'vitest';
// OLD CODE: import { getThreatReport, getBeaconing, getLateralMovement, getDnsAnomalies, getThreatIntel } from './threats'; (NET-192 PR 3: threatRequest)
// OLD CODE: import { getThreatReport, getBeaconing, getLateralMovement, getDnsAnomalies, getThreatIntel, isSnapshotWindow, threatRequest } from './threats'; (the drill-downs)
import { getBeaconPair, getFailedLookups, getThreatReport, getBeaconing, getLateralMovement, getDnsAnomalies, getThreatIntel, isSnapshotWindow, threatRequest } from './threats';
import { BEACON_PAIR, FAILED_LOOKUPS } from '../../../e2e/visual/fixtures/threats';

describe('threats API client', () => {
	it('exports all fetch functions', () => {
		expect(typeof getThreatReport).toBe('function');
		expect(typeof getBeaconing).toBe('function');
		expect(typeof getLateralMovement).toBe('function');
		expect(typeof getDnsAnomalies).toBe('function');
		expect(typeof getThreatIntel).toBe('function');
	});
});

// NET-192 PR 3: the Threats page's pills, as requests
describe('threatRequest', () => {
	const BOUNDS = { from: '2026-11-07T11:00:00.000Z', to: '2026-11-07T12:00:00.000Z' };

	it.each(['24h', '7d', '30d'] as const)('reads the background beaconing scan for %s', (range) => {
		expect(isSnapshotWindow(range)).toBe(true);
		expect(threatRequest(range, BOUNDS)).toEqual({ snapshot: range });
	});

	it.each(['1h', '6h'])('scans %s live over the page’s own bounds', (range) => {
		expect(isSnapshotWindow(range)).toBe(false);
		expect(threatRequest(range, BOUNDS)).toEqual(BOUNDS);
	});
});

// NET-238: false when the alert scan stopped at its cap; an older daemon sends no flag
describe('getThreatIntel', () => {
	afterEach(() => vi.unstubAllGlobals());

	it.each([
		[{ complete: true }, true],
		[{ complete: false }, false],
		[{}, true],
	])('reads complete from %o as %s', async (flag, expected) => {
		const body = { from: '', to: '', new_indicators: 0, feeds: {}, total_indicators: 0, ...flag };
		vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => body })));
		expect((await getThreatIntel()).complete).toBe(expected);
	});
});

describe('the report and beaconing requests', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('send ?snapshot= and nothing else for a snapshot request', async () => {
		const fetchMock = vi.fn(async (_url: string) => ({ ok: true, json: async () => ({}) }));
		vi.stubGlobal('fetch', fetchMock);
		await getThreatReport({ snapshot: '7d' });
		await getBeaconing({ snapshot: '30d' });
		expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
			'/api/threats/report?snapshot=7d',
			'/api/threats/beaconing?snapshot=30d',
		]);
	});
});

// The Threats page's drill-downs: one beaconing pair, and one device's failed lookups
describe('drill-down clients', () => {
	afterEach(() => vi.unstubAllGlobals());
	const reply = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });

	it('asks for the pair with its port, window and bucket', async () => {
		const fetchMock = vi.fn(async () => reply(200, BEACON_PAIR));
		vi.stubGlobal('fetch', fetchMock);
		await expect(getBeaconPair('2001:db8::1', '203.0.113.45', 8080, 'a', 'b', '5m')).resolves.toEqual(BEACON_PAIR);
		const url = new URL(String((fetchMock.mock.calls[0] as unknown[])[0]), 'http://x');
		expect(url.pathname).toBe('/api/threats/beaconing/pair');
		expect(Object.fromEntries(url.searchParams)).toEqual({ device: '2001:db8::1', server: '203.0.113.45', port: '8080', from: 'a', to: 'b', interval: '5m' });
	});

	it('asks for the failed lookups of one device, encoded', async () => {
		const fetchMock = vi.fn(async () => reply(200, FAILED_LOOKUPS));
		vi.stubGlobal('fetch', fetchMock);
		await expect(getFailedLookups('fe80::1', 'a', 'b')).resolves.toEqual(FAILED_LOOKUPS);
		expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toBe('/api/threats/failed-lookups/fe80%3A%3A1?from=a&to=b');
	});

	it("throws the daemon's reason, and a malformed reply instead of showing it", async () => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(503, { error: 'Working this out took too long. Try a shorter time range.' })));
		await expect(getBeaconPair('x', 'y', 1, 'a', 'b')).rejects.toThrow('Try a shorter time range');
		for (const bad of [
			{ ...BEACON_PAIR, timing: { ...BEACON_PAIR.timing, status: 'maybe' } },
			{ ...BEACON_PAIR, threat_intel: undefined },
			{ ...BEACON_PAIR, port: '8080' },
		]) {
			vi.stubGlobal('fetch', vi.fn(async () => reply(200, bad)));
			await expect(getBeaconPair('x', 'y', 1, 'a', 'b')).rejects.toThrow('malformed');
		}
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, { ...FAILED_LOOKUPS, failed_names: [{ name: 'x' }] })));
		await expect(getFailedLookups('x', 'a', 'b')).rejects.toThrow('malformed');
		vi.stubGlobal('fetch', vi.fn(async () => reply(400, { error: 'Invalid IP address: x' })));
		await expect(getFailedLookups('x', 'a', 'b')).rejects.toThrow('Invalid IP address: x');
	});

	it('accepts a pair whose blocklist check could not run', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => reply(200, { ...BEACON_PAIR, threat_intel: null })));
		await expect(getBeaconPair('x', 'y', 1, 'a', 'b')).resolves.toMatchObject({ threat_intel: null });
	});
});
