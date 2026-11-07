import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Tests for web/src/routes/api/[...path]/+server.ts (kept here because some
 * glob-based coverage checks cannot resolve bracket characters in directory names).
 */
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const { GET, POST } = await import('./[...path]/+server.js');

function event(path: string) {
	const url = new URL(`https://nettap.local${path}`);
	const controller = new AbortController();
	return { url, request: new Request(url, { signal: controller.signal }), controller };
}

describe('API Catch-All Proxy Route ([...path]/+server.ts)', () => {
	beforeEach(() => {
		daemonFetch.mockReset();
		daemonFetch.mockResolvedValue(
			new Response(JSON.stringify({ ok: true }), { headers: { 'Content-Type': 'application/json' } }),
		);
	});

	it('proxies ordinary paths with the default timeout', async () => {
		const res = await GET(event('/api/live/dashboard?x=1') as never);
		expect(await res.json()).toEqual({ ok: true });
		const [path, options, timeout] = daemonFetch.mock.calls[0];
		expect(path).toBe('/api/live/dashboard?x=1');
		expect(options.signal).toBeUndefined();
		expect(timeout).toBeUndefined(); // daemonFetch's 10 s default
	});

	it("forwards the heatmap's time zone to the daemon", async () => {
		await GET(event('/api/bandwidth/heatmap?from=a&to=b&tz=America%2FLos_Angeles') as never);
		expect(daemonFetch.mock.calls[0][0]).toBe('/api/bandwidth/heatmap?from=a&to=b&tz=America%2FLos_Angeles');
	});

	it('gives tshark previews 60 s', async () => {
		await GET(event('/api/pcap/preview?file=a.pcap') as never);
		expect(daemonFetch.mock.calls[0][2]).toBe(60_000);
	});

	it('gives the certificate overview 60 s, more than its own 50 s budget', async () => {
		await GET(event('/api/certificates/overview?from=a&to=b') as never);
		expect(daemonFetch.mock.calls[0][2]).toBe(60_000);
	});

	it('keeps 60 s for a filtered certificate overview', async () => {
		await GET(event('/api/certificates/overview?from=a&to=b&site=example.com&server=203.0.113.9') as never);
		expect(daemonFetch.mock.calls[0][2]).toBe(60_000);
	});

	// NET-160: the daemon's drill-down budget is 25 s; the default 10 s would cut it off as unreachable
	it.each(['/api/addresses/203.0.113.9?from=a&to=b', '/api/addresses/2001%3Adb8%3A%3A1', '/api/domains/example.com?from=a&to=b'])(
		'gives %s 30 s',
		async (path) => {
			await GET(event(path) as never);
			expect(daemonFetch.mock.calls[0][2]).toBe(30_000);
		},
	);

	// PR 2 (reliability): 14.4 s cold at 7 d on the G11, past the 10 s default
	it('gives the connection stats 30 s', async () => {
		await GET(event('/api/traffic/connections/stats?from=a&to=b') as never);
		expect(daemonFetch.mock.calls[0][2]).toBe(30_000);
	});

	// NET-192 PR 3: Connections offers 30d again, so its sankey and timeline get the same 30 s
	it.each(['/api/traffic/connections/sankey?from=a&to=b', '/api/traffic/connections/timeline?from=a&to=b&interval=1d'])(
		'gives %s 30 s',
		async (path) => {
			await GET(event(path) as never);
			expect(daemonFetch.mock.calls[0][2]).toBe(30_000);
		},
	);

	// NET-188: the daemon stops a packet search or one packet's detail at ~48 s
	it.each([
		['/api/packets/search', 55_000],
		['/api/packets/packet', 55_000],
		['/api/packets/captures', 15_000],
		['/api/packets/fields?prefix=http.re', 25_000],
		['/api/packets/check-filter', 25_000],
	])('gives %s %i ms', async (path, ms) => {
		await GET(event(path) as never);
		expect(daemonFetch.mock.calls[0][2]).toBe(ms);
	});

	it('posts a packet search with its body, timed and not tied to the browser', async () => {
		const url = new URL('https://nettap.local/api/packets/search');
		const body = JSON.stringify({ filter: 'dns', from: '1700000000.25', to: '1700000600', limit: 100 });
		await POST({ url, request: new Request(url, { method: 'POST', body, headers: { 'Content-Type': 'application/json' } }) } as never);
		const [path, options, timeout] = daemonFetch.mock.calls[0];
		expect([path, options.method, options.body, timeout]).toEqual(['/api/packets/search', 'POST', body, 55_000]);
		expect(options.signal).toBeUndefined();
	});

	it('streams a saved capture file for as long as the browser keeps reading', async () => {
		daemonFetch.mockResolvedValue(
			new Response('pcapbytes', {
				headers: { 'Content-Type': 'application/vnd.tcpdump.pcap', 'Content-Disposition': 'attachment; filename="b.pcap"' },
			}),
		);
		const ev = event('/api/packets/capture-file?id=2026%2Fb.pcap');
		const res = await GET(ev as never);
		const [path, options, timeout] = daemonFetch.mock.calls[0];
		expect([path, timeout]).toEqual(['/api/packets/capture-file?id=2026%2Fb.pcap', undefined]);
		ev.controller.abort();
		expect((options.signal as AbortSignal).aborted).toBe(true);
		expect(await res.text()).toBe('pcapbytes');
		expect(res.headers.get('content-disposition')).toContain('b.pcap');
	});

	it('passes a daemon 503 through with its reason', async () => {
		daemonFetch.mockResolvedValue(
			new Response(JSON.stringify({ error: 'busy' }), { status: 503, headers: { 'Content-Type': 'application/json' } }),
		);
		const res = await GET(event('/api/addresses/203.0.113.9') as never);
		expect(res.status).toBe(503);
		expect(await res.json()).toEqual({ error: 'busy' });
	});

	it('lets PCAP downloads run as long as the browser keeps the request open', async () => {
		for (const path of ['/api/pcap/download-file?file=a.pcap', '/api/pcap/download?filter=dns']) {
			daemonFetch.mockClear();
			const ev = event(path);
			await GET(ev as never);
			const signal: AbortSignal = daemonFetch.mock.calls[0][1].signal;
			expect(signal.aborted).toBe(false);
			ev.controller.abort();
			expect(signal.aborted).toBe(true); // tied to the browser request, not a 10 s timer
		}
	});

	it('streams PCAP bodies through unchanged', async () => {
		daemonFetch.mockResolvedValue(
			new Response('pcapbytes', {
				headers: { 'Content-Type': 'application/vnd.tcpdump.pcap', 'Content-Disposition': 'attachment; filename="a.pcap"' },
			}),
		);
		const res = await GET(event('/api/pcap/download-file?file=a.pcap') as never);
		expect(await res.text()).toBe('pcapbytes');
		expect(res.headers.get('content-disposition')).toContain('a.pcap');
	});
});
