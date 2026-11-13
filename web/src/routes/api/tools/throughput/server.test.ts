import { describe, it, expect, vi, beforeEach } from 'vitest';

// NET-266: the timeout and body forwarding are covered with the other tools in tools-timeouts.test.ts
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a), TOOL_TIMEOUT_MS: { throughput: 55_000 } }));

const { POST } = await import('./+server.js');
const post = (body: string) => POST({ request: new Request('https://nettap.local/api/tools/throughput', { method: 'POST', body }) } as never);

describe('POST /api/tools/throughput', () => {
	beforeEach(() => daemonFetch.mockReset());

	it('answers 400 for a body that is not JSON, without calling the daemon', async () => {
		const res = await post('not json');
		expect(res.status).toBe(400);
		expect(daemonFetch).not.toHaveBeenCalled();
	});

	it("passes the daemon's status and sentence through (a test already running is 409)", async () => {
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ error: 'A throughput test is already running.' }), { status: 409 }));
		const res = await post('{"host":"nas.lan","direction":"upload"}');
		expect(res.status).toBe(409);
		expect(await res.json()).toEqual({ error: 'A throughput test is already running.' });
	});
});
