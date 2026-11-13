import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * NET-203: on the G11 (2026-11-07) a DNS lookup took 15 s and the route gave the daemon its 10 s
 * default, so the page said "Daemon unreachable" while the daemon was still answering. Every Tools
 * route now waits 5 s past the daemon's own limit for that tool.
 */
const daemonFetch = vi.fn();
// OLD CODE: const TOOL_TIMEOUT_MS = { 'dns-recon': 15_000, 'dns-compare': 15_000, ping: 20_000, traceroute: 35_000, 'ssl-cert': 25_000 }; (NET-266)
const TOOL_TIMEOUT_MS = { 'dns-recon': 15_000, 'dns-compare': 15_000, ping: 20_000, traceroute: 35_000, 'ssl-cert': 25_000, throughput: 55_000 };
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a), TOOL_TIMEOUT_MS }));

const routes = {
	'dns-recon': await import('./dns-recon/+server.js'),
	'dns-compare': await import('./dns-compare/+server.js'),
	ping: await import('./ping/+server.js'),
	traceroute: await import('./traceroute/+server.js'),
	'ssl-cert': await import('./ssl-cert/+server.js'),
	throughput: await import('./throughput/+server.js'),
};

describe('Tools proxies wait past the daemon', () => {
	beforeEach(() => {
		daemonFetch.mockReset();
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ ok: true })));
	});

	it.each(Object.entries(routes))('gives %s its own time limit and forwards the body', async (tool, route) => {
		const request = new Request(`https://nettap.local/api/tools/${tool}`, { method: 'POST', body: JSON.stringify({ target: 'example.com' }) });
		const res = await route.POST({ request } as never);
		expect(res.status).toBe(200);
		expect(daemonFetch).toHaveBeenCalledWith(
			`/api/tools/${tool}`,
			{ method: 'POST', body: JSON.stringify({ target: 'example.com' }) },
			TOOL_TIMEOUT_MS[tool as keyof typeof TOOL_TIMEOUT_MS],
		);
	});
});

describe('Tools proxies refuse a body that is not JSON', () => {
	it.each(Object.entries(routes))('%s answers 400 without calling the daemon', async (tool, route) => {
		daemonFetch.mockReset();
		const request = new Request(`https://nettap.local/api/tools/${tool}`, { method: 'POST', body: '{not json' });
		const res = await route.POST({ request } as never);
		expect(res.status).toBe(400);
		expect(await res.json()).toEqual({ error: 'Invalid JSON request body.' });
		expect(daemonFetch).not.toHaveBeenCalled();
	});
});

describe('Tools time limits (the real values)', () => {
	it('sit 5 s above each daemon limit, all under nginx 60 s', async () => {
		const real = await vi.importActual<typeof import('$lib/server/daemon')>('$lib/server/daemon');
		// the daemon's own limits: dns_recon QUERY_TIMEOUT 10 (recon and compare), PING_TIMEOUT 15, TRACEROUTE_TIMEOUT 30, CERT_TIMEOUT 10 x 2,
		// throughput MAX_DURATION 30 + DEADLINE_SLACK 20
		// OLD CODE: expect(real.TOOL_TIMEOUT_MS).toEqual({ 'dns-recon': 15_000, 'dns-compare': 15_000, ping: 20_000, traceroute: 35_000, 'ssl-cert': 25_000 }); (NET-266)
		expect(real.TOOL_TIMEOUT_MS).toEqual({ 'dns-recon': 15_000, 'dns-compare': 15_000, ping: 20_000, traceroute: 35_000, 'ssl-cert': 25_000, throughput: 55_000 });
		for (const ms of Object.values(real.TOOL_TIMEOUT_MS)) expect(ms).toBeLessThan(60_000);
	});
});
