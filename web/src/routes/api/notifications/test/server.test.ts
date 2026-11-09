import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { POST } from './+server';

// F3: the test always answered success, even with no channel set up or a webhook that refused it.

vi.mock('fs', async (importOriginal) => {
	const actual = await importOriginal<typeof import('fs')>();
	return { ...actual, existsSync: vi.fn().mockReturnValue(false), writeFileSync: vi.fn(), mkdirSync: vi.fn() };
});

const ENV = ['SMTP_HOST', 'SMTP_PORT', 'NOTIFY_EMAIL', 'NOTIFY_WEBHOOK_URL', 'NOTIFY_SEVERITY_THRESHOLD'];

async function post() {
	const res = await POST({} as unknown as Parameters<typeof POST>[0]);
	return { status: res.status, body: await res.json() };
}

describe('POST /api/notifications/test', () => {
	beforeEach(() => {
		for (const key of ENV) delete process.env[key];
		vi.spyOn(console, 'error').mockImplementation(() => {});
	});

	afterEach(() => {
		for (const key of ENV) delete process.env[key];
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it('answers 409 when no email or webhook is set up', async () => {
		const fetchMock = vi.fn();
		vi.stubGlobal('fetch', fetchMock);

		const { status, body } = await post();

		expect(status).toBe(409);
		expect(body).toEqual({ error: 'No email or webhook is set up, so there is nothing to test.' });
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it('answers 502 and names the channel when the webhook answers non-2xx', async () => {
		process.env.NOTIFY_WEBHOOK_URL = 'https://hooks.example.com/x';
		vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 500 })));

		const { status, body } = await post();

		expect(status).toBe(502);
		expect(body.error).toBe("The test didn't go through: webhook (HTTP 500).");
		expect(body.results).toEqual([{ channel: 'webhook', ok: false, error: 'HTTP 500' }]);
	});

	it('answers 502 when the webhook cannot be reached', async () => {
		process.env.NOTIFY_WEBHOOK_URL = 'https://hooks.example.com/x';
		vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('fetch failed'); }));

		const { status, body } = await post();

		expect(status).toBe(502);
		expect(body.error).toBe("The test didn't go through: webhook (fetch failed).");
	});

	it('answers 200 only when every channel took it, whatever the severity threshold', async () => {
		process.env.NOTIFY_WEBHOOK_URL = 'https://hooks.example.com/x';
		// critical only: a medium test would have been held back by the normal dispatch
		process.env.NOTIFY_SEVERITY_THRESHOLD = '1';
		const fetchMock = vi.fn(async (_url: string) => new Response(null, { status: 204 }));
		vi.stubGlobal('fetch', fetchMock);

		const { status, body } = await post();

		expect(status).toBe(200);
		expect(body).toEqual({ success: true, results: [{ channel: 'webhook', ok: true }] });
		expect(fetchMock).toHaveBeenCalledTimes(1);
		expect(fetchMock.mock.calls[0][0]).toBe('https://hooks.example.com/x');
	});
});
