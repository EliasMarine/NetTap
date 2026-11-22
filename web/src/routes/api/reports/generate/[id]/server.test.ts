/** NET-340: Generate now waits up to 60 s for the daemon's report, and passes its 409 through unchanged. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { daemonFetch } from '$lib/server/daemon.js';
import { POST } from './+server';

vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: vi.fn() }));

type Event = Parameters<typeof POST>[0];
const ID = '0b6f1c1e-4f7a-4c2e-9d3b-2a1f5e6c7d80';

function daemonReply(status: number, body: unknown) {
	vi.mocked(daemonFetch).mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('report generate proxy', () => {
	afterEach(() => vi.mocked(daemonFetch).mockReset());

	it('gives the daemon 60 s, not the 10 s default', async () => {
		daemonReply(200, { id: '20261117T080012Z-a1b2c3' });
		const res = await POST({ params: { id: ID } } as unknown as Event);

		expect(daemonFetch).toHaveBeenCalledWith(`/api/reports/generate/${ID}`, { method: 'POST' }, 60_000);
		expect(res.status).toBe(200);
	});

	it("passes the daemon's 409 and its sentence through", async () => {
		const error = "A report is being generated. It will appear in the history when it's done.";
		daemonReply(409, { error });
		const res = await POST({ params: { id: ID } } as unknown as Event);

		expect(res.status).toBe(409);
		expect(await res.json()).toEqual({ error });
	});
});
