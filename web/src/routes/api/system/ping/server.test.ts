import { describe, it, expect, vi, beforeEach } from 'vitest';

const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const { GET } = await import('./+server.js');

describe('GET /api/system/ping', () => {
	beforeEach(() => daemonFetch.mockReset());

	it("passes on the daemon's liveness answer", async () => {
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ status: 'ok', uptime: 5 })));
		const res = await GET({} as never);
		expect(daemonFetch).toHaveBeenCalledWith('/api/health', undefined, 5_000);
		expect(res.status).toBe(200);
		expect(await res.json()).toEqual({ status: 'ok', uptime: 5 });
	});

	it('passes on the error status when the daemon is unreachable', async () => {
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ error: 'Daemon unreachable' }), { status: 502 }));
		const res = await GET({} as never);
		expect(res.status).toBe(502);
	});
});
