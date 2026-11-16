import { describe, it, expect, vi } from 'vitest';

/** The check asks GitHub twice (15 s each): the 10 s default cut it off while the daemon finished it. */
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', async (importOriginal) => {
	const real = await importOriginal<typeof import('$lib/server/daemon.js')>();
	return { ...real, daemonFetch: (...a: unknown[]) => daemonFetch(...a) };
});

const { POST } = await import('./+server.js');
const { UPDATE_CHECK_TIMEOUT_MS } = await import('$lib/server/daemon.js');

describe('POST /api/system/updates/check proxy', () => {
	it('gives the daemon the update check time limit and relays its answer', async () => {
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ updates: [], stale: false }), { status: 200 }));

		const res = await POST({} as never);

		expect(daemonFetch).toHaveBeenCalledWith('/api/system/updates/check', { method: 'POST' }, UPDATE_CHECK_TIMEOUT_MS);
		expect(UPDATE_CHECK_TIMEOUT_MS).toBeGreaterThan(30_000); // two 15 s GitHub calls
		expect(UPDATE_CHECK_TIMEOUT_MS).toBeLessThan(60_000); // nginx's proxy_read_timeout
		expect(res.status).toBe(200);
		expect(await res.json()).toEqual({ updates: [], stale: false });
	});
});
