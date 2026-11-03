import { describe, it, expect, vi, afterEach } from 'vitest';
import { daemonJSON } from '$lib/server/daemon.js';
import { POST } from './+server';

vi.mock('$lib/server/daemon.js', () => ({ daemonJSON: vi.fn() }));

async function post(body: unknown) {
	const request = new Request('http://localhost/api/setup/configure', {
		method: 'POST',
		body: JSON.stringify(body),
	});
	const res = await POST({ request } as Parameters<typeof POST>[0]);
	return { status: res.status, body: await res.json() };
}

describe('POST /api/setup/configure', () => {
	afterEach(() => {
		vi.mocked(daemonJSON).mockReset();
	});

	it('forwards the body to the daemon with a 60 s timeout', async () => {
		vi.mocked(daemonJSON).mockResolvedValue({ data: { status: 'ok' }, status: 200 });
		const payload = { capture_mode: 'dhcp_gateway', capture_interface: 'eth1' };

		const { status, body } = await post(payload);

		expect(daemonJSON).toHaveBeenCalledWith(
			'/api/setup/configure',
			expect.objectContaining({ method: 'POST', body: JSON.stringify(payload) }),
			60_000
		);
		expect(status).toBe(200);
		expect(body).toEqual({ status: 'ok' });
	});

	it('returns the daemon error and status', async () => {
		vi.mocked(daemonJSON).mockResolvedValue({ error: 'dhcp_subnet must be private', status: 400 });

		const { status, body } = await post({ capture_mode: 'dhcp_gateway' });

		expect(status).toBe(400);
		expect(body).toEqual({ error: 'dhcp_subnet must be private' });
	});
});
