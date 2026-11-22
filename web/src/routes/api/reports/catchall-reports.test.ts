/**
 * NET-340: the card's save and the report history have no route files of their own; the catch-all
 * forwards them, the PUT body unchanged and the daemon's 409 sentence intact.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const { GET, PUT } = await import('../[...path]/+server.js');

function event(path: string, init?: RequestInit) {
	const url = new URL(`https://nettap.local${path}`);
	return { url, params: { path: url.pathname.replace(/^\/api\//, '') }, request: new Request(url, init) };
}

const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('report routes through the catch-all', () => {
	beforeEach(() => daemonFetch.mockReset());

	it('PUT /api/reports/card forwards the confirming body and passes a 409 through', async () => {
		const body = JSON.stringify({ enabled: true, weekday: 0, hour: 8, recipients: ['a@example.com'], confirm: true, confirm_token: 't', rev: 3 });
		daemonFetch.mockResolvedValue(reply(409, { error: 'A report is being sent. Try again in a minute.' }));

		const res = await PUT(event('/api/reports/card', { method: 'PUT', body, headers: { 'Content-Type': 'application/json' } }) as never);

		const [path, options] = daemonFetch.mock.calls[0];
		expect(path).toBe('/api/reports/card');
		expect(options).toMatchObject({ method: 'PUT', body });
		expect(res.status).toBe(409);
		expect(await res.json()).toEqual({ error: 'A report is being sent. Try again in a minute.' });
	});

	it('GET /api/reports/history keeps its schedule query', async () => {
		daemonFetch.mockResolvedValue(reply(200, { reports: [] }));
		await GET(event('/api/reports/history?schedule=6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b') as never);
		expect(daemonFetch.mock.calls[0][0]).toBe('/api/reports/history?schedule=6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b');
	});
});
