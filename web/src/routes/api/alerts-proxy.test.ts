import { describe, it, expect, vi } from 'vitest';

// #146/#147: the alert tables' sort and a category's sub-category must reach the daemon through this whitelist
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const alerts = await import('./alerts/+server.js');

describe('alert list proxy', () => {
	it('forwards the sort, order and sub-category with the filters and paging', async () => {
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ ok: true })));
		const url = new URL('https://nettap.local/api/alerts?from=a&to=b&page=3&size=25&category=scan&sub=port_scan&sort=severity&order=desc&other=x');
		await alerts.GET({ url } as never);
		expect(daemonFetch).toHaveBeenCalledWith('/api/alerts?from=a&to=b&page=3&size=25&category=scan&sort=severity&order=desc&sub=port_scan');
	});
});
