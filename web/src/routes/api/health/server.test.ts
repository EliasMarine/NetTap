import { describe, it, expect, vi, afterEach } from 'vitest';
import { daemonFetch } from '$lib/server/daemon.js';
import { GET } from './+server';

// F6: this route is public (Docker healthchecks, the setup wizard) and passed on the daemon's full
// system health: the drive's SMART serial and model, storage figures. It needs the liveness answer only.

vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: vi.fn() }));

async function get() {
	const res = await GET({} as unknown as Parameters<typeof GET>[0]);
	return { status: res.status, body: await res.json() };
}

const FULL_HEALTH = {
	status: 'ok',
	uptime: 12.5,
	smart: { serial: 'S6XNNS0T123456', model: 'Samsung SSD 980 1TB' },
	storage: { disk_usage_percent: 42 },
};

describe('GET /api/health', () => {
	afterEach(() => vi.mocked(daemonFetch).mockReset());

	it("asks the daemon's light /api/health and passes on its status only", async () => {
		vi.mocked(daemonFetch).mockResolvedValue(new Response(JSON.stringify(FULL_HEALTH), { status: 200 }));

		const { status, body } = await get();

		expect(daemonFetch).toHaveBeenCalledWith('/api/health');
		expect(status).toBe(200);
		expect(body.status).toBe('healthy');
		expect(body.daemon).toEqual({ status: 'ok' });
		const text = JSON.stringify(body);
		for (const leak of ['serial', 'smart', 'storage', 'S6XNNS0T123456', 'model']) expect(text).not.toContain(leak);
	});

	it('says unreachable, still with 200, when the daemon answers an error', async () => {
		vi.mocked(daemonFetch).mockResolvedValue(new Response('', { status: 503 }));

		const { status, body } = await get();

		expect(status).toBe(200);
		expect(body.daemon).toEqual({ status: 'unreachable', error: 'Daemon returned HTTP 503' });
	});

	it('says unreachable when the daemon cannot be reached', async () => {
		vi.mocked(daemonFetch).mockRejectedValue(new TypeError('fetch failed'));

		const { status, body } = await get();

		expect(status).toBe(200);
		expect(body.daemon).toEqual({ status: 'unreachable', error: 'Could not connect to daemon' });
	});
});
