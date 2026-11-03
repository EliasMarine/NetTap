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
});
