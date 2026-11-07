// @vitest-environment node
import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * NET-188: POST /api/packets/download. The daemon aborts its stream when the packets stop
 * verifying part-way; the browser must then see a failed download, not a short file.
 */
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const { POST, DOWNLOAD_HEADERS_TIMEOUT_MS } = await import('./+server.js');

const MANIFEST = {
	from: '1700000000.25',
	to: '1700000600',
	filter: 'dns',
	files: [{ id: 'a.pcap', size: 10, mtime_ns: '9223372036854775807', recent: false }],
	frames: [{ n: 1, t: '1700000001.5', cap_len: 60, md5: 'd41d8cd98f00b204e9800998ecf8427e' }],
};
const URL_ = 'https://nettap.local/api/packets/download';

function post(body: string, contentType: string) {
	const controller = new AbortController();
	const request = new Request(URL_, {
		method: 'POST',
		body,
		headers: { 'Content-Type': contentType },
		signal: controller.signal,
	});
	return { event: { request, url: new URL(URL_) } as never, controller };
}

/** A pcap stream that sends two chunks, then ends cleanly or errors. */
function pcapStream(fail: boolean): Response {
	const chunks = [new Uint8Array([0xd4, 0xc3]), new Uint8Array([0xb2, 0xa1])];
	return new Response(
		new ReadableStream({
			pull(controller) {
				const next = chunks.shift();
				if (next) controller.enqueue(next);
				else if (fail) controller.error(new TypeError('terminated'));
				else controller.close();
			},
		}),
		{
			headers: {
				'Content-Type': 'application/vnd.tcpdump.pcap',
				'Content-Disposition': 'attachment; filename="nettap-packets-20231114T221320Z.pcap"',
			},
		},
	);
}

describe('POST /api/packets/download', () => {
	beforeEach(() => {
		daemonFetch.mockReset();
		daemonFetch.mockResolvedValue(pcapStream(false));
	});

	it('forwards a JSON manifest unchanged', async () => {
		const { event } = post(JSON.stringify({ manifest: MANIFEST }), 'application/json');
		const res = await POST(event);

		const [path, options, timeout] = daemonFetch.mock.calls[0];
		expect(path).toBe('/api/packets/download');
		expect(options.method).toBe('POST');
		expect(options.body).toBe(JSON.stringify({ manifest: MANIFEST }));
		expect(options.body).toContain('"mtime_ns":"9223372036854775807"');
		expect(timeout).toBeUndefined();
		expect((options.signal as AbortSignal).aborted).toBe(false); // no 10 s cut-off mid-file

		expect(res.status).toBe(200);
		expect(res.headers.get('content-type')).toBe('application/vnd.tcpdump.pcap');
		expect(res.headers.get('content-disposition')).toContain('nettap-packets-');
		expect([...new Uint8Array(await res.arrayBuffer())]).toEqual([0xd4, 0xc3, 0xb2, 0xa1]);
	});

	it('accepts a urlencoded form post', async () => {
		const body = new URLSearchParams({ manifest: JSON.stringify(MANIFEST) }).toString();
		const { event } = post(body, 'application/x-www-form-urlencoded');
		expect((await POST(event)).status).toBe(200);
		expect(JSON.parse(daemonFetch.mock.calls[0][1].body)).toEqual({ manifest: MANIFEST });
	});

	it('accepts a multipart form post', async () => {
		const boundary = 'nettapboundary';
		const body = [
			`--${boundary}`,
			'Content-Disposition: form-data; name="manifest"',
			'',
			JSON.stringify(MANIFEST),
			`--${boundary}--`,
			'',
		].join('\r\n');
		const { event } = post(body, `multipart/form-data; boundary=${boundary}`);
		expect((await POST(event)).status).toBe(200);
		expect(JSON.parse(daemonFetch.mock.calls[0][1].body)).toEqual({ manifest: MANIFEST });
	});

	it.each([
		['no manifest', JSON.stringify({}), 'application/json'],
		['a manifest that is not an object', JSON.stringify({ manifest: 'x' }), 'application/json'],
		['an array manifest', JSON.stringify({ manifest: [] }), 'application/json'],
		['broken JSON', '{"manifest":', 'application/json'],
		['a form field that is not JSON', 'manifest=%7Bnope', 'application/x-www-form-urlencoded'],
		['a form without the field', 'other=1', 'application/x-www-form-urlencoded'],
		['another content type', JSON.stringify({ manifest: MANIFEST }), 'text/plain'],
	])('answers 400 for %s without calling the daemon', async (_name, body, type) => {
		const res = await POST(post(body, type).event);
		expect(res.status).toBe(400);
		expect((await res.json()).error).toBeTruthy();
		expect(daemonFetch).not.toHaveBeenCalled();
	});

	it.each([409, 503, 507])("passes the daemon's %i through with its reason", async (status) => {
		daemonFetch.mockResolvedValue(
			new Response(JSON.stringify({ error: 'The saved captures changed.', detail: 'a.pcap' }), { status }),
		);
		const res = await POST(post(JSON.stringify({ manifest: MANIFEST }), 'application/json').event);
		expect(res.status).toBe(status);
		expect(await res.json()).toEqual({ error: 'The saved captures changed.', detail: 'a.pcap' });
	});

	it('gives up when the daemon sends no headers in time', async () => {
		vi.useFakeTimers();
		try {
			let signal: AbortSignal | undefined;
			daemonFetch.mockImplementation(
				(_path: string, options: RequestInit) =>
					new Promise((_resolve, reject) => {
						signal = options.signal ?? undefined;
						signal?.addEventListener('abort', () => reject(new Error('aborted')));
					}),
			);
			const outcome = POST(post(JSON.stringify({ manifest: MANIFEST }), 'application/json').event).then(
				() => 'answered',
				(e: Error) => e.message,
			);
			await vi.advanceTimersByTimeAsync(DOWNLOAD_HEADERS_TIMEOUT_MS - 1);
			expect(signal?.aborted).toBe(false);
			await vi.advanceTimersByTimeAsync(1);
			expect(signal?.aborted).toBe(true);
			expect(await outcome).toBe('aborted');
		} finally {
			vi.useRealTimers();
		}
	});

	it('keeps the status when the daemon error is not JSON', async () => {
		daemonFetch.mockResolvedValue(new Response('<html>oops</html>', { status: 500 }));
		const res = await POST(post(JSON.stringify({ manifest: MANIFEST }), 'application/json').event);
		expect(res.status).toBe(500);
		expect((await res.json()).error).toBe('Failed to parse daemon response');
	});

	it('fails the download when the daemon stream errors after two chunks', async () => {
		daemonFetch.mockResolvedValue(pcapStream(true));
		const res = await POST(post(JSON.stringify({ manifest: MANIFEST }), 'application/json').event);
		expect(res.status).toBe(200); // the headers had already gone out
		await expect(res.arrayBuffer()).rejects.toThrow('terminated');
	});
});
