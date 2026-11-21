/**
 * NET-344: a backup download goes through the catch-all proxy byte for byte, so the size the daemon
 * fitted it to is the size that restores. Its errors stay JSON, and the busy 503 keeps Retry-After.
 */
import { describe, it, expect, vi, afterAll, afterEach } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const dir = mkdtempSync(join(tmpdir(), 'nettap-token-'));
writeFileSync(join(dir, 'token'), 'test-token');
process.env.DAEMON_TOKEN_FILE = join(dir, 'token');
const { GET } = await import('./[...path]/+server.js');

const EXPORT = '/api/backup/export';

function event(path: string) {
	const url = new URL(`https://nettap.local${path}`);
	return { url, params: { path: url.pathname.replace(/^\/api\//, '') }, request: new Request(url) };
}

function daemonAnswers(response: Response) {
	const fn = vi.fn().mockResolvedValue(response);
	vi.stubGlobal('fetch', fn);
	return fn;
}

describe('catch-all proxy: backup export', () => {
	afterEach(() => vi.unstubAllGlobals());
	afterAll(() => rmSync(dir, { recursive: true, force: true }));

	it("passes the daemon's bytes and its three headers through unchanged", async () => {
		// compact, an emoji, an escaped lone surrogate and a number JSON.stringify would rewrite
		const body = '{"metadata":{"x":1e-05,"acknowledgements_left_out":3},"sections":{"n":"🎮 \\ud800"}}';
		daemonAnswers(
			new Response(body, {
				status: 200,
				headers: {
					'Content-Type': 'application/json; charset=utf-8',
					'Content-Disposition': 'attachment; filename="nettap-config-2026-11-20.json"',
					'Cache-Control': 'no-store',
				},
			}),
		);
		const res = await GET(event(EXPORT) as never);

		expect(res.status).toBe(200);
		expect(res.headers.get('content-type')).toBe('application/json; charset=utf-8');
		expect(res.headers.get('content-disposition')).toBe('attachment; filename="nettap-config-2026-11-20.json"');
		expect(res.headers.get('cache-control')).toBe('no-store');
		expect(await res.text()).toBe(body);
	});

	it('gives the export the slow-path allowance', async () => {
		const timeout = vi.spyOn(AbortSignal, 'timeout');
		daemonAnswers(new Response('{}', { status: 200 }));
		await GET(event(EXPORT) as never);
		expect(timeout).toHaveBeenCalledWith(60_000);
		timeout.mockRestore();
	});

	it.each([
		[413, { error: 'This backup would be 17.4 MB, over the 16 MB restore limit.', code: 'backup_too_large' }],
		[422, { error: 'Excluded IPs: 10.0.0.0/8 is a range.', code: 'legacy_excluded_ips' }],
	])('keeps a %i export error as JSON', async (status, payload) => {
		daemonAnswers(new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } }));
		const res = await GET(event(EXPORT) as never);

		expect(res.status).toBe(status);
		expect(res.headers.get('content-disposition')).toBeNull();
		expect(await res.json()).toEqual(payload);
	});

	it("keeps the busy 503's Retry-After", async () => {
		const payload = { error: 'A backup is already being made. Try again in a moment.' };
		daemonAnswers(
			new Response(JSON.stringify(payload), {
				status: 503,
				headers: { 'Content-Type': 'application/json', 'Retry-After': '30' },
			}),
		);
		const res = await GET(event(EXPORT) as never);

		expect(res.status).toBe(503);
		expect(res.headers.get('retry-after')).toBe('30');
		expect(await res.json()).toEqual(payload);
	});

	it('still re-encodes every other JSON reply, adding no headers it lacked', async () => {
		daemonAnswers(new Response('{ "ok" : true }', { status: 200, headers: { 'Content-Type': 'application/json' } }));
		const res = await GET(event('/api/live/stats') as never);

		expect(await res.text()).toBe('{"ok":true}');
		expect(res.headers.get('retry-after')).toBeNull();
		expect(res.headers.get('cache-control')).toBeNull();
	});
});
