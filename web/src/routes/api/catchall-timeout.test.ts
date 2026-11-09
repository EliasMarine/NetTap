/**
 * NET-160: the catch-all proxy with the real daemonFetch. The address and domain endpoints can
 * take up to their 25 s budget, so a 12 s answer must reach the page, where the 10 s default
 * would have turned it into "Daemon unreachable".
 */
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const dir = mkdtempSync(join(tmpdir(), 'nettap-token-'));
writeFileSync(join(dir, 'token'), 'test-token');
process.env.DAEMON_TOKEN_FILE = join(dir, 'token');
const { GET, POST } = await import('./[...path]/+server.js');

const DELAY_MS = 12_000;

function event(path: string) {
	const url = new URL(`https://nettap.local${path}`);
	return { url, request: new Request(url) };
}

/** The daemon answers after DELAY_MS unless the request's signal aborts first. */
function slowDaemon() {
	vi.stubGlobal(
		'fetch',
		vi.fn(
			(_url: string, init: RequestInit) =>
				new Promise((resolve, reject) => {
					const timer = setTimeout(() => resolve(new Response(JSON.stringify({ ip: 'ok' }), { status: 200 })), DELAY_MS);
					init.signal?.addEventListener('abort', () => {
						clearTimeout(timer);
						reject(new Error('The operation was aborted due to timeout'));
					});
				}),
		),
	);
}

describe('catch-all proxy timeouts with the real daemonFetch', () => {
	beforeAll(() => {
		vi.useFakeTimers();
		// AbortSignal.timeout runs on Node's own clock; drive it from the fake one
		vi.spyOn(AbortSignal, 'timeout').mockImplementation((ms: number) => {
			const controller = new AbortController();
			setTimeout(() => controller.abort(), ms);
			return controller.signal;
		});
	});
	afterEach(() => vi.unstubAllGlobals());
	afterAll(() => {
		vi.useRealTimers();
		vi.restoreAllMocks();
		rmSync(dir, { recursive: true, force: true });
	});

	it('lets a 12 s address answer through', async () => {
		slowDaemon();
		const pending = GET(event('/api/addresses/203.0.113.9?from=a&to=b') as never);
		await vi.advanceTimersByTimeAsync(DELAY_MS);
		const res = await pending;
		expect(res.status).toBe(200);
		expect(await res.json()).toEqual({ ip: 'ok' });
	});

	it('lets a 12 s domain answer through', async () => {
		slowDaemon();
		const pending = GET(event('/api/domains/example.com') as never);
		await vi.advanceTimersByTimeAsync(DELAY_MS);
		expect((await pending).status).toBe(200);
	});

	it('lets a 12 s Suricata category answer through (NET-160 slice 2b-2)', async () => {
		slowDaemon();
		const pending = GET(event(`/api/alerts/suricata/${encodeURIComponent('A/B & C')}?from=a&to=b`) as never);
		await vi.advanceTimersByTimeAsync(DELAY_MS);
		expect((await pending).status).toBe(200);
	});

	// NET-224: a channel test waits for the daemon's send, up to 40 s for a slow mail server
	it('lets a 12 s channel test answer through, with its reason', async () => {
		slowDaemon();
		const url = new URL('https://nettap.local/api/notifications/channels/ch1/test');
		const pending = POST({ url, request: new Request(url, { method: 'POST' }) } as never);
		await vi.advanceTimersByTimeAsync(DELAY_MS);
		expect((await pending).status).toBe(200);
	});

	it('would have cut the same answer off at the 10 s default (the check above is real)', async () => {
		slowDaemon();
		const pending = GET(event('/api/live/dashboard') as never);
		await vi.advanceTimersByTimeAsync(DELAY_MS);
		const res = await pending;
		expect(res.status).toBe(502);
		expect((await res.json()).error).toMatch(/^Daemon unreachable/);
	});

	it("passes the daemon's 503 reason through, not \"Daemon unreachable\"", async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'busy' }), { status: 503 })));
		const res = await GET(event('/api/addresses/203.0.113.9') as never);
		expect(res.status).toBe(503);
		expect(await res.json()).toEqual({ error: 'busy' });
	});
});
