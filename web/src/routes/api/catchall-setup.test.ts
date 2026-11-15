import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * NET-290: the catch-all proxy never forwards /api/setup/*. Every call the wizard makes there has its own
 * route file, so a path that reaches the catch-all is a route that was removed or never existed. The daemon's
 * POST /api/setup/bridge is a real bridge build; before this, deleting the web route (which only calls the
 * read-only preview) would have sent the wizard's call straight to it.
 * (Kept in src/routes/api/ for the same reason as catchall-proxy.test.ts: bracketed directory names.)
 */
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const { GET, POST, PUT, DELETE } = await import('./[...path]/+server.js');

/** What SvelteKit hands the catch-all: the URL as sent, and the matched rest-parameter already decoded. */
function event(path: string) {
	const url = new URL(`https://nettap.local${path}`);
	const rest = decodeURIComponent(url.pathname.replace(/^\/api\//, ''));
	return { url, params: { path: rest }, request: new Request(url) };
}

describe('catch-all proxy and /api/setup (NET-290)', () => {
	beforeEach(() => {
		daemonFetch.mockReset();
		daemonFetch.mockResolvedValue(
			new Response(JSON.stringify({ ok: true }), { headers: { 'Content-Type': 'application/json' } }),
		);
	});

	const HANDLERS = { GET, POST, PUT, DELETE };

	it.each(
		Object.keys(HANDLERS).flatMap((method) =>
			[
				'/api/setup/bridge',
				'/api/setup/configure',
				'/api/setup/bridge/preview',
				'/api/setup',
				'/api/setup/other?x=1',
				// percent-encoded: aiohttp decodes these when it routes, so the guard must look at the decoded path
				'/api/%73etup/bridge',
				'/api/setup%2Fbridge',
			].map((path) => [method, path]),
		),
	)('%s %s answers 404 and never reaches the daemon', async (method, path) => {
		const res = await HANDLERS[method as keyof typeof HANDLERS](event(path) as never);
		expect(res.status).toBe(404);
		expect(await res.json()).toEqual({ error: 'Not found' });
		expect(daemonFetch).not.toHaveBeenCalled();
	});

	it.each(['/api/setupx', '/api/dhcp/setup/leases', '/api/live/dashboard'])('still proxies %s', async (path) => {
		const res = await GET(event(path) as never);
		expect(res.status).toBe(200);
		expect(daemonFetch.mock.calls[0][0]).toBe(path);
	});
});
