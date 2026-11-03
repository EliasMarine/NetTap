import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Tests for web/src/routes/api/[...path]/+server.ts (kept here because some
 * glob-based coverage checks cannot resolve bracket characters in directory names).
 */
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const { GET } = await import('./[...path]/+server.js');

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
