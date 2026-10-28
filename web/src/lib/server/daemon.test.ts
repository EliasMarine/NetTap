import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { daemonFetch, daemonJSON } from './daemon';

// ---------------------------------------------------------------------------
// Mock global fetch
// ---------------------------------------------------------------------------

const originalFetch = globalThis.fetch;

beforeEach(() => {
	globalThis.fetch = vi.fn();
});

afterEach(() => {
	globalThis.fetch = originalFetch;
});

// ---------------------------------------------------------------------------
// daemonFetch
// ---------------------------------------------------------------------------

describe('daemonFetch', () => {
	it('builds URL from daemon base + path', async () => {
		const mockResponse = new Response(JSON.stringify({ ok: true }), {
			status: 200,
			headers: { 'Content-Type': 'application/json' },
		});
		vi.mocked(globalThis.fetch).mockResolvedValue(mockResponse);

		await daemonFetch('/api/traffic/summary');

		expect(globalThis.fetch).toHaveBeenCalledWith(
			'http://nettap-storage-daemon:8880/api/traffic/summary',
			expect.objectContaining({
				headers: expect.objectContaining({
					'Content-Type': 'application/json',
				}),
			})
		);
	});

	it('forwards request options', async () => {
		const mockResponse = new Response('{}', { status: 200 });
		vi.mocked(globalThis.fetch).mockResolvedValue(mockResponse);

		await daemonFetch('/api/test', {
			method: 'POST',
			body: JSON.stringify({ key: 'value' }),
		});

		expect(globalThis.fetch).toHaveBeenCalledWith(
			expect.any(String),
			expect.objectContaining({
				method: 'POST',
				body: '{"key":"value"}',
			})
		);
	});

	it('sets default Content-Type header', async () => {
		const mockResponse = new Response('{}', { status: 200 });
		vi.mocked(globalThis.fetch).mockResolvedValue(mockResponse);

		await daemonFetch('/api/test');

		const callArgs = vi.mocked(globalThis.fetch).mock.calls[0][1] as RequestInit;
		expect((callArgs.headers as Record<string, string>)['Content-Type']).toBe(
			'application/json'
		);
	});

	it('sets default AbortSignal timeout', async () => {
		const mockResponse = new Response('{}', { status: 200 });
		vi.mocked(globalThis.fetch).mockResolvedValue(mockResponse);

		await daemonFetch('/api/test');

		const callArgs = vi.mocked(globalThis.fetch).mock.calls[0][1] as RequestInit;
		expect(callArgs.signal).toBeInstanceOf(AbortSignal);
	});

	it('allows overriding signal', async () => {
		const mockResponse = new Response('{}', { status: 200 });
		vi.mocked(globalThis.fetch).mockResolvedValue(mockResponse);

		const customSignal = AbortSignal.timeout(5_000);
		await daemonFetch('/api/test', { signal: customSignal });

		const callArgs = vi.mocked(globalThis.fetch).mock.calls[0][1] as RequestInit;
		expect(callArgs.signal).toBe(customSignal);
	});

	it('returns 502 Response on connection error', async () => {
		vi.mocked(globalThis.fetch).mockRejectedValue(new Error('ECONNREFUSED'));

		const result = await daemonFetch('/api/test');
		const body = await result.json();

		expect(result.status).toBe(502);
		expect(body.error).toContain('Daemon unreachable');
		expect(body.error).toContain('ECONNREFUSED');
		expect(body.daemonAvailable).toBe(false);
	});

	it('returns 502 on unknown error type', async () => {
		vi.mocked(globalThis.fetch).mockRejectedValue('string error');

		const result = await daemonFetch('/api/test');
		const body = await result.json();

		expect(result.status).toBe(502);
		expect(body.error).toContain('Unknown error');
	});

	it('returns successful daemon response as-is', async () => {
		const data = { connections: [], count: 0 };
		const mockResponse = new Response(JSON.stringify(data), {
			status: 200,
			headers: { 'Content-Type': 'application/json' },
		});
		vi.mocked(globalThis.fetch).mockResolvedValue(mockResponse);

		const result = await daemonFetch('/api/live/connections');

		expect(result.status).toBe(200);
		const body = await result.json();
		expect(body).toEqual(data);
	});
});

// ---------------------------------------------------------------------------
// daemonJSON
// ---------------------------------------------------------------------------

describe('daemonJSON', () => {
	it('returns parsed data on success', async () => {
		const payload = { devices: [{ ip: '192.168.1.1' }] };
		const mockResponse = new Response(JSON.stringify(payload), {
			status: 200,
			headers: { 'Content-Type': 'application/json' },
		});
		vi.mocked(globalThis.fetch).mockResolvedValue(mockResponse);

		const result = await daemonJSON('/api/devices');

		expect(result.status).toBe(200);
		expect(result.data).toEqual(payload);
		expect(result.error).toBeUndefined();
	});

	it('returns error on non-ok status', async () => {
		const mockResponse = new Response(
			JSON.stringify({ error: 'Not found' }),
			{ status: 404, headers: { 'Content-Type': 'application/json' } }
		);
		vi.mocked(globalThis.fetch).mockResolvedValue(mockResponse);

		const result = await daemonJSON('/api/missing');

		expect(result.status).toBe(404);
		expect(result.error).toBe('Not found');
		expect(result.data).toBeUndefined();
	});

	it('returns fallback error message when response has no error field', async () => {
		const mockResponse = new Response(
			JSON.stringify({ detail: 'something' }),
			{ status: 500, headers: { 'Content-Type': 'application/json' } }
		);
		vi.mocked(globalThis.fetch).mockResolvedValue(mockResponse);

		const result = await daemonJSON('/api/broken');

		expect(result.status).toBe(500);
		expect(result.error).toBe('Daemon returned 500');
	});

	it('handles non-JSON response gracefully', async () => {
		const mockResponse = new Response('Internal Server Error', {
			status: 500,
			headers: { 'Content-Type': 'text/plain' },
		});
		vi.mocked(globalThis.fetch).mockResolvedValue(mockResponse);

		const result = await daemonJSON('/api/broken');

		expect(result.status).toBe(500);
		expect(result.error).toBe('Failed to parse daemon response');
	});

	it('handles daemon unreachable (502 from daemonFetch)', async () => {
		vi.mocked(globalThis.fetch).mockRejectedValue(new Error('fetch failed'));

		const result = await daemonJSON('/api/test');

		expect(result.status).toBe(502);
		expect(result.error).toContain('Daemon unreachable');
	});
});
