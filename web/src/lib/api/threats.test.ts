import { describe, it, expect, vi, afterEach } from 'vitest';
// OLD CODE: import { getThreatReport, getBeaconing, getLateralMovement, getDnsAnomalies, getThreatIntel } from './threats'; (NET-192 PR 3: threatRequest)
import { getThreatReport, getBeaconing, getLateralMovement, getDnsAnomalies, getThreatIntel, threatRequest } from './threats';

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
	const NOW = new Date('2026-11-07T12:00:00Z');

	it.each(['24h', '7d', '30d'] as const)('reads the background beaconing scan for %s', (range) => {
		expect(threatRequest(range, NOW)).toEqual({ snapshot: range });
	});

	it.each([
		['1h', 3600_000],
		['6h', 6 * 3600_000],
	])('scans %s live, ending now', (range, ms) => {
		const r = threatRequest(range, NOW);
		expect(r).toEqual({ from: new Date(NOW.getTime() - ms).toISOString(), to: NOW.toISOString() });
	});

	it('treats an unknown range as 24h, like the page', () => {
		expect(threatRequest('15m', NOW)).toEqual({ snapshot: '24h' });
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
