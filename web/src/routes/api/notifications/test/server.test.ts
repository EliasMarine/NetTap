// OLD CODE START — NET-224: F3's route sent from the web container's env; the daemon sends and tests now
// import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
// import { POST } from './+server';
//
// // F3: the test always answered success, even with no channel set up or a webhook that refused it.
//
// vi.mock('fs', async (importOriginal) => {
// 	const actual = await importOriginal<typeof import('fs')>();
// 	return { ...actual, existsSync: vi.fn().mockReturnValue(false), writeFileSync: vi.fn(), mkdirSync: vi.fn() };
// });
//
// const ENV = ['SMTP_HOST', 'SMTP_PORT', 'NOTIFY_EMAIL', 'NOTIFY_WEBHOOK_URL', 'NOTIFY_SEVERITY_THRESHOLD'];
//
// async function post() {
// 	const res = await POST({} as unknown as Parameters<typeof POST>[0]);
// 	return { status: res.status, body: await res.json() };
// }
//
// describe('POST /api/notifications/test', () => {
// 	beforeEach(() => {
// 		for (const key of ENV) delete process.env[key];
// 		vi.spyOn(console, 'error').mockImplementation(() => {});
// 	});
//
// 	afterEach(() => {
// 		for (const key of ENV) delete process.env[key];
// 		vi.unstubAllGlobals();
// 		vi.restoreAllMocks();
// 	});
//
// 	it('answers 409 when no email or webhook is set up', async () => {
// 		const fetchMock = vi.fn();
// 		vi.stubGlobal('fetch', fetchMock);
//
// 		const { status, body } = await post();
//
// 		expect(status).toBe(409);
// 		expect(body).toEqual({ error: 'No email or webhook is set up, so there is nothing to test.' });
// 		expect(fetchMock).not.toHaveBeenCalled();
// 	});
//
// 	it('answers 502 and names the channel when the webhook answers non-2xx', async () => {
// 		process.env.NOTIFY_WEBHOOK_URL = 'https://hooks.example.com/x';
// 		vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 500 })));
//
// 		const { status, body } = await post();
//
// 		expect(status).toBe(502);
// 		expect(body.error).toBe("The test didn't go through: webhook (HTTP 500).");
// 		expect(body.results).toEqual([{ channel: 'webhook', ok: false, error: 'HTTP 500' }]);
// 	});
//
// 	it('answers 502 when the webhook cannot be reached', async () => {
// 		process.env.NOTIFY_WEBHOOK_URL = 'https://hooks.example.com/x';
// 		vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('fetch failed'); }));
//
// 		const { status, body } = await post();
//
// 		expect(status).toBe(502);
// 		expect(body.error).toBe("The test didn't go through: webhook (fetch failed).");
// 	});
//
// 	it('answers 200 only when every channel took it, whatever the severity threshold', async () => {
// 		process.env.NOTIFY_WEBHOOK_URL = 'https://hooks.example.com/x';
// 		// critical only: a medium test would have been held back by the normal dispatch
// 		process.env.NOTIFY_SEVERITY_THRESHOLD = '1';
// 		const fetchMock = vi.fn(async (_url: string) => new Response(null, { status: 204 }));
// 		vi.stubGlobal('fetch', fetchMock);
//
// 		const { status, body } = await post();
//
// 		expect(status).toBe(200);
// 		expect(body).toEqual({ success: true, results: [{ channel: 'webhook', ok: true }] });
// 		expect(fetchMock).toHaveBeenCalledTimes(1);
// 		expect(fetchMock.mock.calls[0][0]).toBe('https://hooks.example.com/x');
// 	});
// });
// OLD CODE END

import { describe, it, expect, vi, beforeEach } from 'vitest';

// NET-224: the daemon tests every enabled channel; this route relays its answer and reason
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const { POST } = await import('./+server');

async function post(status: number, body: unknown) {
	daemonFetch.mockResolvedValue(new Response(JSON.stringify(body), { status }));
	const res = await POST({} as never);
	return { status: res.status, body: await res.json() };
}

describe('POST /api/notifications/test', () => {
	beforeEach(() => daemonFetch.mockReset());

	it('asks the daemon, with time for a slow mail server', async () => {
		await post(200, { success: true, results: [] });
		expect(daemonFetch).toHaveBeenCalledWith('/api/notifications/test', { method: 'POST' }, 60_000);
	});

	it.each([
		[200, { success: true, results: [{ channel_id: 'settings-webhook', ok: true }] }],
		[409, { error: 'No notification channel is set up, so there is nothing to test.' }],
		[502, { error: "The test didn't go through: Webhook (Settings) (HTTP 500).", results: [] }],
	])('passes the daemon\'s %i and its reason through', async (status, body) => {
		expect(await post(status, body)).toEqual({ status, body });
	});

	// review L1: a 200 the page can't read is not "sent"
	it('answers 502 when the daemon\'s 200 has no readable body', async () => {
		daemonFetch.mockResolvedValue(new Response('<html>not json</html>', { status: 200 }));
		const res = await POST({} as never);
		expect(res.status).toBe(502);
		expect((await res.json()).error).toMatch(/couldn't be read/);
	});
});
