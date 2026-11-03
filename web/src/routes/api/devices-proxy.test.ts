import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * /api/devices/{ip} also serves /api/devices/registry; it forwarded only from/to, so Home's
 * registry list lost its limit (asked 200, got the daemon's default 100).
 */
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const single = await import('./devices/[ip]/+server.js');
const connections = await import('./devices/[ip]/connections/+server.js');

describe('device detail / registry proxy', () => {
	beforeEach(() => {
		daemonFetch.mockReset();
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ ok: true })));
	});

	it('forwards the registry list limit', async () => {
		const url = new URL('https://nettap.local/api/devices/registry?limit=200');
		await single.GET({ params: { ip: 'registry' }, url } as never);
		expect(daemonFetch).toHaveBeenCalledWith('/api/devices/registry?limit=200');
	});

	it('still forwards a device detail time range', async () => {
		const url = new URL('https://nettap.local/api/devices/192.168.1.5?from=a&to=b');
		await single.GET({ params: { ip: '192.168.1.5' }, url } as never);
		expect(daemonFetch).toHaveBeenCalledWith('/api/devices/192.168.1.5?from=a&to=b');
	});

	// #143: the device page's column sort (#140) never reached the daemon
	it("forwards a device's connection sort and order with the paging", async () => {
		const url = new URL('https://nettap.local/api/devices/192.168.1.5/connections?from=a&to=b&page=2&size=50&sort=dl&order=asc&other=x');
		await connections.GET({ params: { ip: '192.168.1.5' }, url } as never);
		expect(daemonFetch).toHaveBeenCalledWith('/api/devices/192.168.1.5/connections?from=a&to=b&page=2&size=50&sort=dl&order=asc');
	});
});
