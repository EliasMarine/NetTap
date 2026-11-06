import { describe, it, expect, vi } from 'vitest';

// #145: the Connections page's sort and State filter must reach the daemon through this whitelist
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const connections = await import('./traffic/connections/+server.js');

describe('connection list proxy', () => {
	it('forwards the sort, order and state with the paging and search', async () => {
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ ok: true })));
		const url = new URL('https://nettap.local/api/traffic/connections?from=a&to=b&page=2&size=50&q=dns&sort=source&order=asc&state=rejected&other=x');
		await connections.GET({ url } as never);
		expect(daemonFetch).toHaveBeenCalledWith('/api/traffic/connections?from=a&to=b&page=2&size=50&q=dns&sort=source&order=asc&state=rejected');
	});

	// NET-160: the structured address filter; an allowlist that dropped it would list every session
	it.each(['203.0.113.9', '2001:db8::1'])('forwards ip=%s intact with the search, paging and sort', async (ip) => {
		daemonFetch.mockReset();
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ ok: true })));
		const url = new URL('https://nettap.local/api/traffic/connections');
		for (const [k, v] of Object.entries({ from: 'a', to: 'b', page: '3', size: '25', q: 'tls', sort: 'time', order: 'desc', ip })) url.searchParams.set(k, v);
		await connections.GET({ url } as never);
		const sent = new URL(daemonFetch.mock.calls[0][0] as string, 'http://daemon');
		expect(sent.pathname).toBe('/api/traffic/connections');
		expect(Object.fromEntries(sent.searchParams)).toEqual({ from: 'a', to: 'b', page: '3', size: '25', q: 'tls', sort: 'time', order: 'desc', ip });
	});
});
