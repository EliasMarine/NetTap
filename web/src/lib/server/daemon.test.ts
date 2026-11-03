import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
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

// ---------------------------------------------------------------------------
// Shared daemon token (X-NetTap-Daemon-Token)
// ---------------------------------------------------------------------------

describe('daemonFetch token', () => {
	const TOKEN_HEADER = 'X-NetTap-Daemon-Token';
	let dir: string;
	let tokenFile: string;
	let fetchDaemon: typeof daemonFetch;

	const sentHeaders = (call: number) =>
		vi.mocked(globalThis.fetch).mock.calls[call][1]?.headers as Record<string, string>;

	beforeEach(async () => {
		dir = mkdtempSync(join(tmpdir(), 'nettap-daemon-token-'));
		tokenFile = join(dir, 'daemon-token');
		vi.stubEnv('DAEMON_TOKEN_FILE', tokenFile);
		vi.resetModules();
		({ daemonFetch: fetchDaemon } = await import('./daemon'));
	});

	afterEach(() => {
		vi.unstubAllEnvs();
		vi.restoreAllMocks();
		rmSync(dir, { recursive: true, force: true });
	});

	it('sends the token read from the token file', async () => {
		writeFileSync(tokenFile, 'token-a\n');
		vi.mocked(globalThis.fetch).mockResolvedValue(new Response('{}', { status: 200 }));

		await fetchDaemon('/api/system/health');

		expect(sentHeaders(0)[TOKEN_HEADER]).toBe('token-a');
		expect(sentHeaders(0)['Content-Type']).toBe('application/json');
	});

	it('still calls the daemon without a header when the file is missing', async () => {
		const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
		vi.mocked(globalThis.fetch).mockResolvedValue(new Response('{}', { status: 401 }));

		const res = await fetchDaemon('/api/system/health');

		expect(res.status).toBe(401);
		expect(globalThis.fetch).toHaveBeenCalledTimes(1);
		expect(sentHeaders(0)[TOKEN_HEADER]).toBeUndefined();
		expect(logged).toHaveBeenCalledTimes(1);
	});

	it('caches the token until the daemon rejects it', async () => {
		writeFileSync(tokenFile, 'token-a');
		vi.mocked(globalThis.fetch).mockImplementation(async () => new Response('{}', { status: 200 }));

		await fetchDaemon('/api/one');
		writeFileSync(tokenFile, 'token-b');
		await fetchDaemon('/api/two');

		expect(sentHeaders(1)[TOKEN_HEADER]).toBe('token-a');
	});

	it('re-reads the token after a 401 and retries once with the new one', async () => {
		writeFileSync(tokenFile, 'token-a');
		vi.mocked(globalThis.fetch).mockResolvedValueOnce(new Response('{}', { status: 200 }));
		await fetchDaemon('/api/warm-cache');

		writeFileSync(tokenFile, 'token-b');
		vi.mocked(globalThis.fetch)
			.mockResolvedValueOnce(new Response('{"error":"Unauthorized"}', { status: 401 }))
			.mockResolvedValueOnce(new Response('{"ok":true}', { status: 200 }));

		const res = await fetchDaemon('/api/storage/prune', { method: 'POST', body: '{}' });

		expect(res.status).toBe(200);
		expect(sentHeaders(1)[TOKEN_HEADER]).toBe('token-a');
		expect(sentHeaders(2)[TOKEN_HEADER]).toBe('token-b');
		expect(vi.mocked(globalThis.fetch).mock.calls[2][1]?.method).toBe('POST');
	});

	it('does not retry when the re-read token is unchanged', async () => {
		writeFileSync(tokenFile, 'token-a');
		vi.mocked(globalThis.fetch).mockResolvedValue(new Response('{}', { status: 401 }));

		const res = await fetchDaemon('/api/system/health');

		expect(res.status).toBe(401);
		expect(globalThis.fetch).toHaveBeenCalledTimes(1);
	});

	it('never puts the token in the unreachable-daemon error body', async () => {
		writeFileSync(tokenFile, 'secret-token-value');
		vi.mocked(globalThis.fetch).mockRejectedValue(new Error('ECONNREFUSED'));

		const res = await fetchDaemon('/api/system/health');

		expect(res.status).toBe(502);
		expect(await res.text()).not.toContain('secret-token-value');
	});
});
