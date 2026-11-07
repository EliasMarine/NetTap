import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * /threats failed on the G11 (2026-11-07): the report's beaconing scan takes ~13 s over 24 h and the
 * routes gave the daemon the 10 s default, so the page got a 502 instead of the report.
 */
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a), THREAT_SCAN_TIMEOUT_MS: 120_000 }));

const report = await import('./threats/report/+server.js');
const beaconing = await import('./threats/beaconing/+server.js');

describe('threat scan proxies', () => {
	beforeEach(() => {
		daemonFetch.mockReset();
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ ok: true })));
	});

	it.each([
		['report', report],
		['beaconing', beaconing],
	])('gives the %s scan 120 s and forwards its window', async (name, route) => {
		const url = new URL(`https://nettap.local/api/threats/${name}?from=a&to=b`);
		await route.GET({ url } as never);
		expect(daemonFetch).toHaveBeenCalledWith(`/api/threats/${name}?from=a&to=b`, undefined, 120_000);
	});
});
