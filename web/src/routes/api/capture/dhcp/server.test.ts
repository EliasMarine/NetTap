import { describe, it, expect, vi, afterEach } from 'vitest';
import { daemonFetch } from '$lib/server/daemon.js';
import { POST as enablePOST } from './enable/+server';
import { POST as disablePOST } from './disable/+server';

vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: vi.fn() }));

function daemonReply(status: number, body: unknown) {
	vi.mocked(daemonFetch).mockResolvedValue(
		new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
	);
}

function post(path: string, body?: unknown) {
	return new Request(`http://localhost${path}`, {
		method: 'POST',
		...(body !== undefined ? { body: JSON.stringify(body) } : {}),
	});
}

type Event = Parameters<typeof enablePOST>[0];
type DisableEvent = Parameters<typeof disablePOST>[0];

describe('DHCP gateway proxy routes (60 s timeout)', () => {
	afterEach(() => {
		vi.mocked(daemonFetch).mockReset();
	});

	it('enable forwards the confirm body to the daemon with a 60 s timeout', async () => {
		daemonReply(200, { dhcp_enabled: true, capture_restart: { restarted: [], errors: [] } });

		const res = await enablePOST({ request: post('/api/capture/dhcp/enable', { confirm: true }) } as Event);

		expect(daemonFetch).toHaveBeenCalledWith(
			'/api/capture/dhcp/enable',
			{ method: 'POST', body: '{"confirm":true}' },
			60_000
		);
		expect(res.status).toBe(200);
		expect(await res.json()).toMatchObject({ dhcp_enabled: true });
	});

	it('enable passes daemon refusals through with their status and checks', async () => {
		const checks = [{ name: 'no_other_dhcp', passed: false, blocking: true, message: 'Router DHCP on' }];
		daemonReply(409, { error: 'not yet', checks });

		const res = await enablePOST({ request: post('/api/capture/dhcp/enable', { confirm: true }) } as Event);

		expect(res.status).toBe(409);
		expect(await res.json()).toEqual({ error: 'not yet', checks });
	});

	it('enable reports a daemon timeout as 502 with the daemon error', async () => {
		daemonReply(502, { error: 'Daemon unreachable: aborted due to timeout', daemonAvailable: false });

		const res = await enablePOST({ request: post('/api/capture/dhcp/enable', { confirm: true }) } as Event);

		expect(res.status).toBe(502);
		expect((await res.json()).error).toMatch(/timeout/);
	});

	it('disable forwards a POST with a 60 s timeout', async () => {
		daemonReply(200, { dhcp_enabled: false });

		const res = await disablePOST({ request: post('/api/capture/dhcp/disable') } as DisableEvent);

		expect(daemonFetch).toHaveBeenCalledWith('/api/capture/dhcp/disable', { method: 'POST' }, 60_000);
		expect(res.status).toBe(200);
		expect(await res.json()).toEqual({ dhcp_enabled: false });
	});

	it('returns a parse error when the daemon answers with non-JSON', async () => {
		vi.mocked(daemonFetch).mockResolvedValue(new Response('<html>', { status: 500 }));

		const res = await disablePOST({ request: post('/api/capture/dhcp/disable') } as DisableEvent);

		expect(res.status).toBe(500);
		expect(await res.json()).toEqual({ error: 'Failed to parse daemon response' });
	});
});
