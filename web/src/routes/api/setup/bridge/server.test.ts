import { describe, it, expect, vi, afterEach } from 'vitest';
import { daemonJSON } from '$lib/server/daemon.js';
import { POST } from './+server';

vi.mock('$lib/server/daemon.js', () => ({ daemonJSON: vi.fn() }));

const PAIR = { wan_interface: 'enp2s0', lan_interface: 'enp3s0' };

async function post(body: unknown) {
	const request = new Request('http://localhost/api/setup/bridge', {
		method: 'POST',
		body: JSON.stringify(body),
	});
	const res = await POST({ request } as Parameters<typeof POST>[0]);
	return { status: res.status, body: await res.json() };
}

describe('POST /api/setup/bridge (wizard Verify, CR-004)', () => {
	afterEach(() => {
		vi.mocked(daemonJSON).mockReset();
	});

	it('asks the daemon for a preview, never the bridge create endpoint', async () => {
		const preview = { config_preview: 'BRIDGE_NAME=br0', wan: 'enp2s0', lan: 'enp3s0', bridge_name: 'br0', ready: true, warnings: [], source: 'daemon' };
		vi.mocked(daemonJSON).mockResolvedValue({ data: preview, status: 200 });

		const { status, body } = await post(PAIR);

		expect(daemonJSON).toHaveBeenCalledWith(
			'/api/setup/bridge/preview',
			expect.objectContaining({ method: 'POST', body: JSON.stringify(PAIR) })
		);
		expect(status).toBe(200);
		expect(body).toEqual(preview);
	});

	it('returns the daemon refusal instead of a verified mock', async () => {
		const refusal = 'enp2s0 has an IP address (192.168.1.50), so this machine uses it';
		vi.mocked(daemonJSON).mockResolvedValue({ error: refusal, status: 400 });

		const { status, body } = await post(PAIR);

		expect(status).toBe(400);
		expect(body).toEqual({ error: refusal });
		expect(body).not.toHaveProperty('ready');
	});

	it('reports an unreachable daemon as an error, not as verified', async () => {
		vi.mocked(daemonJSON).mockResolvedValue({ error: 'Daemon unreachable: ECONNREFUSED', status: 502 });

		const { status, body } = await post(PAIR);

		expect(status).toBe(502);
		expect(body.error).toMatch(/Daemon unreachable/);
	});

	it('rejects the same port twice without calling the daemon', async () => {
		const { status } = await post({ wan_interface: 'enp2s0', lan_interface: 'enp2s0' });

		expect(status).toBe(400);
		expect(daemonJSON).not.toHaveBeenCalled();
	});
});
