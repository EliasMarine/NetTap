/**
 * NET-200: a device's photo goes through the catch-all proxy as an image, with the daemon's
 * caching and safety headers, and the picture endpoint's 404 no-store reaches the browser, so a
 * stale `?v=` miss is never cached under a URL that later holds the photo again.
 */
import { describe, it, expect, vi, afterAll, afterEach } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const dir = mkdtempSync(join(tmpdir(), 'nettap-token-'));
writeFileSync(join(dir, 'token'), 'test-token');
process.env.DAEMON_TOKEN_FILE = join(dir, 'token');
const { GET } = await import('./[...path]/+server.js');

const PICTURE = '/api/devices/registry/AA:BB:CC:DD:EE:FF/picture?v=0123456789abcdef';

function event(path: string) {
	const url = new URL(`https://nettap.local${path}`);
	return { url, request: new Request(url) };
}

function daemonAnswers(response: Response) {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));
}

describe('catch-all proxy: device pictures', () => {
	afterEach(() => vi.unstubAllGlobals());
	afterAll(() => rmSync(dir, { recursive: true, force: true }));

	it('streams the photo through with its type and the daemon headers', async () => {
		const bytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
		daemonAnswers(
			new Response(bytes, {
				status: 200,
				headers: {
					'Content-Type': 'image/png',
					'Cache-Control': 'private, max-age=31536000, immutable',
					'X-Content-Type-Options': 'nosniff',
					'Content-Security-Policy': "default-src 'none'",
				},
			}),
		);
		const res = await GET(event(PICTURE) as never);
		expect(res.status).toBe(200);
		expect(res.headers.get('content-type')).toBe('image/png');
		expect(res.headers.get('cache-control')).toBe('private, max-age=31536000, immutable');
		expect(res.headers.get('x-content-type-options')).toBe('nosniff');
		expect(res.headers.get('content-security-policy')).toBe("default-src 'none'");
		expect(new Uint8Array(await res.arrayBuffer())).toEqual(bytes);
	});

	it("keeps a JSON 404's no-store", async () => {
		daemonAnswers(
			new Response(JSON.stringify({ error: 'No such picture' }), {
				status: 404,
				headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
			}),
		);
		const res = await GET(event(PICTURE) as never);
		expect(res.status).toBe(404);
		expect(res.headers.get('cache-control')).toBe('no-store');
		expect(await res.json()).toEqual({ error: 'No such picture' });
	});

	it('adds no Cache-Control to a JSON reply that had none', async () => {
		daemonAnswers(new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
		const res = await GET(event('/api/live/stats') as never);
		expect(res.headers.get('cache-control')).toBeNull();
	});
});
