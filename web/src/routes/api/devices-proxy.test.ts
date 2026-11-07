import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * /api/devices/{ip} also serves /api/devices/registry; it forwarded only from/to, so Home's
 * registry list lost its limit (asked 200, got the daemon's default 100).
 */
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const list = await import('./devices/+server.js');
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

	// NET-158: the page's protocol filter moved to the daemon; dropping it here showed every protocol
	it("forwards a device's connection protocol filter", async () => {
		const url = new URL('https://nettap.local/api/devices/192.168.1.5/connections?page=1&sort=direction&proto=udp');
		await connections.GET({ params: { ip: '192.168.1.5' }, url } as never);
		expect(daemonFetch).toHaveBeenCalledWith('/api/devices/192.168.1.5/connections?page=1&sort=direction&proto=udp');
	});
});

// NET-160 slice 2b-3: the device check on the box gates the 30-day list at 80% of this route's
// timeout, so the route passes it explicitly and the two values must be the same number.
describe('device list proxy', () => {
	/** DEVICE_LIST_TIMEOUT_MS=… as scripts/remote/deploy-drill-down.sh declares it. */
	function scriptTimeout(): number {
		const script = readFileSync(resolve(process.cwd(), '../scripts/remote/deploy-drill-down.sh'), 'utf-8');
		const match = /^DEVICE_LIST_TIMEOUT_MS=(\d+)$/m.exec(script);
		if (!match) throw new Error('deploy-drill-down.sh declares no DEVICE_LIST_TIMEOUT_MS=');
		return Number(match[1]);
	}

	it("gives the daemon the deploy check's timeout and passes the reading's fields through unchanged", async () => {
		const reply = {
			from: 'a', to: 'b', limit: 500, devices: [], total: 612, as_of: '2026-11-06T12:00:00.123Z',
			online_since: '2026-11-06T11:55:00.123Z', online_total: 41,
		};
		daemonFetch.mockResolvedValue(new Response(JSON.stringify(reply)));
		const url = new URL('https://nettap.local/api/devices?from=a&to=b&sort=bytes&order=desc&limit=500');
		const res = await list.GET({ url } as never);
		expect(daemonFetch).toHaveBeenCalledWith('/api/devices?from=a&to=b&sort=bytes&order=desc&limit=500', undefined, scriptTimeout());
		expect(scriptTimeout()).toBe(10_000);
		expect(await res.json()).toEqual(reply);
	});
});
