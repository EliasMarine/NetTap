import { describe, it, expect, vi, beforeEach } from 'vitest';

// OLD CODE START — NET-224: F3's route answered 501; it saves through the daemon now
// import { POST } from './+server';
//
// // F3: POST threw the body away and answered success, so the page said "saved successfully"
// // when nothing was saved. Email and webhook come from the environment in this version.
//
// async function post(body: unknown) {
// 	const request = new Request('http://localhost/api/notifications/config', {
// 		method: 'POST',
// 		headers: { 'Content-Type': 'application/json' },
// 		body: JSON.stringify(body),
// 	});
// 	const res = await POST({ request } as unknown as Parameters<typeof POST>[0]);
// 	return { status: res.status, body: await res.json() };
// }
//
// describe('POST /api/notifications/config', () => {
// 	it('says nothing was saved (501) instead of reporting success', async () => {
// 		const { status, body } = await post({ severityThreshold: 'high', webhook: { url: 'https://hooks.example.com/x' } });
//
// 		expect(status).toBe(501);
// 		expect(body).toEqual({
// 			error: "Not saved: email and webhook notifications can't be set from this page in this version.",
// 		});
// 		expect(body).not.toHaveProperty('success');
// 	});
// });
// OLD CODE END

// NET-224: the daemon keeps the Settings tab's notification setup; this route only relays it
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const route = await import('./+server');

const SAVED = {
	min_severity: 2,
	email: { enabled: true, recipients: ['admin@example.com'], smtp_configured: true },
	webhook: { enabled: true, has_url: true, url_hint: 'https://hooks.example.com/…' },
};

function answer(status: number, body: unknown) {
	daemonFetch.mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

describe('/api/notifications/config', () => {
	beforeEach(() => daemonFetch.mockReset());

	it("GET relays the daemon's settings", async () => {
		answer(200, SAVED);
		const res = await route.GET({} as never);
		expect(daemonFetch).toHaveBeenCalledWith('/api/notifications/config');
		expect(res.status).toBe(200);
		expect(await res.json()).toEqual(SAVED);
	});

	it('PUT sends the body to the daemon and returns what it saved', async () => {
		answer(200, SAVED);
		const body = { min_severity: 2, email: { enabled: true, recipients: ['admin@example.com'] }, webhook: { enabled: true, url: '' } };
		const request = new Request('http://localhost/api/notifications/config', { method: 'PUT', body: JSON.stringify(body) });

		const res = await route.PUT({ request } as never);

		const [path, init] = daemonFetch.mock.calls[0];
		expect(path).toBe('/api/notifications/config');
		expect(init.method).toBe('PUT');
		expect(JSON.parse(init.body)).toEqual(body);
		expect(res.status).toBe(200);
		expect(await res.json()).toEqual(SAVED);
	});

	it("PUT passes the daemon's refusal and reason through", async () => {
		answer(400, { error: 'Email: set the SMTP server in Settings › API keys first' });
		const request = new Request('http://localhost/api/notifications/config', { method: 'PUT', body: '{}' });

		const res = await route.PUT({ request } as never);

		expect(res.status).toBe(400);
		expect((await res.json()).error).toMatch(/SMTP server/);
	});

	it('no longer answers POST with a 501', () => {
		expect((route as Record<string, unknown>).POST).toBeUndefined();
	});
});
