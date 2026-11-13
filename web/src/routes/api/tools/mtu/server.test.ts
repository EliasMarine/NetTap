import { describe, it, expect, vi, beforeEach } from 'vitest';

// NET-267: the timeout and body forwarding are covered with the other tools in tools-timeouts.test.ts
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a), TOOL_TIMEOUT_MS: { mtu: 35_000 } }));

const { POST } = await import('./+server.js');
const post = (body: string) => POST({ request: new Request('https://nettap.local/api/tools/mtu', { method: 'POST', body }) } as never);

describe('POST /api/tools/mtu', () => {
	beforeEach(() => daemonFetch.mockReset());

	it('answers 400 for a body that is not JSON, without calling the daemon', async () => {
		const res = await post('not json');
		expect(res.status).toBe(400);
		expect(daemonFetch).not.toHaveBeenCalled();
	});

	it("passes the daemon's status and sentence through (two checks running is 503)", async () => {
		const busy = 'Two MTU checks are already running. Try again in a moment.';
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ error: busy }), { status: 503 }));
		const res = await post('{"target":"10.8.0.1"}');
		expect(res.status).toBe(503);
		expect(await res.json()).toEqual({ error: busy });
	});
});
