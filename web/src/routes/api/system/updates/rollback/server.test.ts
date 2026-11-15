import { describe, it, expect, vi, beforeEach } from 'vitest';

/** NET-291 review: a JSON body that is not an object (`null`) threw at `body.component` and became a 500. */
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const { POST } = await import('./+server.js');

const post = (body: unknown) =>
	POST({
		request: new Request('https://nettap.local/api/system/updates/rollback', { method: 'POST', body: JSON.stringify(body) }),
	} as never);

describe('POST /api/system/updates/rollback proxy', () => {
	beforeEach(() => {
		daemonFetch.mockReset();
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ success: true }), { status: 200 }));
	});

	it.each([null, [], 5, 'suricata-rules', {}, { component: 5 }, { component: '' }])(
		'answers 400 itself for the body %j, without asking the daemon',
		async (body) => {
			const res = await post(body);
			expect(res.status).toBe(400);
			expect(daemonFetch).not.toHaveBeenCalled();
		},
	);

	it('answers 400 for text that is not JSON', async () => {
		const res = await POST({
			request: new Request('https://nettap.local/api/system/updates/rollback', { method: 'POST', body: '{nope' }),
		} as never);
		expect(res.status).toBe(400);
		expect(daemonFetch).not.toHaveBeenCalled();
	});

	it('forwards a component name to the daemon and relays its answer', async () => {
		const res = await post({ component: 'suricata-rules' });
		expect(res.status).toBe(200);
		expect(daemonFetch).toHaveBeenCalledWith('/api/system/updates/rollback', {
			method: 'POST',
			body: JSON.stringify({ component: 'suricata-rules' }),
		});
	});
});
