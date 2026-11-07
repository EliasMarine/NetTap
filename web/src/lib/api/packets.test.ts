import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getCaptures,
	searchPackets,
	getPacket,
	checkFilter,
	suggestFields,
	downloadPackets,
	captureFileUrl,
	PacketApiError,
	type PacketManifest,
} from './packets';

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

function mockFetch(body: unknown, status = 200): ReturnType<typeof vi.fn> {
	const fn = vi.fn().mockResolvedValue(
		new Response(typeof body === 'string' ? body : JSON.stringify(body), {
			status,
			headers: { 'Content-Type': 'application/json' },
		}),
	);
	vi.stubGlobal('fetch', fn);
	return fn;
}

/** The URL, method and parsed JSON body of the first fetch call. */
function sent(fn: ReturnType<typeof vi.fn>): { url: string; method: string; body: unknown } {
	const [url, init] = fn.mock.calls[0] as [string, RequestInit | undefined];
	return { url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body as string) : undefined };
}

async function caught(p: Promise<unknown>): Promise<PacketApiError> {
	try {
		await p;
	} catch (e) {
		return e as PacketApiError;
	}
	throw new Error('expected a rejection');
}

function manifest(): PacketManifest {
	return {
		from: '1700000000.25',
		to: '1700000600.123456789',
		filter: 'dns',
		files: [{ id: 'a/b.pcap', size: 1024, mtime_ns: '9223372036854775807', recent: false }],
		frames: [{ n: 7, t: '1700000001.000000001', cap_len: 60, md5: 'd41d8cd98f00b204e9800998ecf8427e' }],
	};
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('packets API client', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	it('getCaptures asks for the capture list', async () => {
		const fn = mockFetch({ files: [], count: 0, oldest_packet: null });
		const result = await getCaptures();
		expect(sent(fn)).toEqual({ url: '/api/packets/captures', method: 'GET', body: undefined });
		expect(result.oldest_packet).toBeNull();
	});

	it('searchPackets posts the search with its times as strings', async () => {
		const fn = mockFetch({ rows: [], termination: 'eof' });
		const body = { filter: 'dns', from: '1700000000.25', to: '1700000600', limit: 250 as const };
		const result = await searchPackets(body);
		expect(sent(fn)).toEqual({ url: '/api/packets/search', method: 'POST', body });
		expect(result.termination).toBe('eof');
		expect((fn.mock.calls[0][1] as RequestInit).headers).toEqual({ 'Content-Type': 'application/json' });
	});

	it('getPacket sends the manifest back unchanged, big decimal strings included', async () => {
		const fn = mockFetch({ n: 7, layers: [] });
		await getPacket(manifest(), 7);
		const { url, method, body } = sent(fn);
		expect([url, method]).toEqual(['/api/packets/packet', 'POST']);
		expect(body).toEqual({ manifest: manifest(), frame: 7 });
		// The raw text, not a re-parse: the value never became a number on the way out
		expect((fn.mock.calls[0][1] as RequestInit).body).toContain('"mtime_ns":"9223372036854775807"');
	});

	it('checkFilter posts the filter', async () => {
		const fn = mockFetch({ ok: true, filter: 'tcp.port == 443' });
		expect(await checkFilter('tcp.port == 443')).toEqual({ ok: true, filter: 'tcp.port == 443' });
		expect(sent(fn)).toEqual({ url: '/api/packets/check-filter', method: 'POST', body: { filter: 'tcp.port == 443' } });
	});

	it("checkFilter rejects with TShark's message on a 400", async () => {
		mockFetch({ error: '"tcp.prot" is neither a field nor a protocol name.' }, 400);
		const err = await caught(checkFilter('tcp.prot'));
		expect(err).toBeInstanceOf(PacketApiError);
		expect(err.status).toBe(400);
		expect(err.message).toBe('"tcp.prot" is neither a field nor a protocol name.');
	});

	it('suggestFields encodes the prefix and passes the abort signal', async () => {
		const fn = mockFetch({ prefix: 'http.re', fields: [], more: false });
		const controller = new AbortController();
		await suggestFields('http.re&x', controller.signal);
		expect(fn.mock.calls[0][0]).toBe('/api/packets/fields?prefix=http.re%26x');
		expect((fn.mock.calls[0][1] as RequestInit).signal).toBe(controller.signal);
	});

	it('captureFileUrl encodes the id', () => {
		expect(captureFileUrl('2026/a b&c.pcap')).toBe('/api/packets/capture-file?id=2026%2Fa+b%26c.pcap');
	});

	it.each([409, 503, 507])('keeps the status and the daemon reason for a %i', async (status) => {
		mockFetch({ error: 'The saved captures changed.', detail: 'a/b.pcap' }, status);
		const err = await caught(searchPackets({ filter: '', from: '1', to: '2', limit: 100 }));
		expect(err).toBeInstanceOf(PacketApiError);
		expect([err.status, err.message, err.detail]).toEqual([status, 'The saved captures changed.', 'a/b.pcap']);
	});

	it('falls back to the HTTP status when the error body is not JSON', async () => {
		mockFetch('<html>Bad gateway</html>', 502);
		const err = await caught(getCaptures());
		expect([err.status, err.message, err.detail]).toEqual([502, 'HTTP 502', undefined]);
	});

	it('rejects a 200 that is not JSON (a sign-in page) with a readable error', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>Sign in</html>', { status: 200 })));
		const err = await caught(getCaptures());
		expect(err).toBeInstanceOf(PacketApiError);
		expect([err.status, err.message]).toEqual([200, 'NetTap sent an unexpected reply. Sign in again and retry.']);
	});

	it('lets a network error through', async () => {
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
		await expect(getCaptures()).rejects.toThrow('Failed to fetch');
	});

	describe('downloadPackets', () => {
		function streamedResponse(fail: boolean): Response {
			const chunks = [new Uint8Array([1, 2]), new Uint8Array([3])];
			return new Response(
				new ReadableStream({
					pull(controller) {
						const next = chunks.shift();
						if (next) controller.enqueue(next);
						else if (fail) controller.error(new TypeError('terminated'));
						else controller.close();
					},
				}),
				{ headers: { 'Content-Type': 'application/vnd.tcpdump.pcap' } },
			);
		}

		it('posts the manifest unchanged and returns the whole file', async () => {
			const fn = vi.fn().mockResolvedValue(streamedResponse(false));
			vi.stubGlobal('fetch', fn);
			const blob = await downloadPackets(manifest());
			expect(sent(fn)).toEqual({ url: '/api/packets/download', method: 'POST', body: { manifest: manifest() } });
			expect([...new Uint8Array(await blob.arrayBuffer())]).toEqual([1, 2, 3]);
		});

		it('rejects when the stream breaks after some bytes, never a short file', async () => {
			vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamedResponse(true)));
			await expect(downloadPackets(manifest())).rejects.toThrow('terminated');
		});

		it('rejects with the status and reason when the daemon refuses up front', async () => {
			mockFetch({ error: 'Not enough space to build the download.' }, 507);
			const err = await caught(downloadPackets(manifest()));
			expect([err.status, err.message]).toEqual([507, 'Not enough space to build the download.']);
		});
	});
});
