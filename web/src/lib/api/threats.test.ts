import { describe, it, expect, vi, afterEach } from 'vitest';
// OLD CODE: import { getThreatReport, getBeaconing, getLateralMovement, getDnsAnomalies, getThreatIntel } from './threats'; (NET-192 PR 3: threatRequest)
import { getThreatReport, getBeaconing, getLateralMovement, getDnsAnomalies, getThreatIntel, isSnapshotWindow, threatRequest } from './threats';

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
