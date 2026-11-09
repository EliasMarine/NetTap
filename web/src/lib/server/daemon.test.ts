import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { daemonFetch, daemonJSON, RULE_UPDATE_TIMEOUT_MS } from './daemon';

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

	// NET-203: the Tools routes' longer limits only help if they reach the abort signal
	it('gives the fetch a time limit of the timeout it was called with', async () => {
		const timeout = vi.spyOn(AbortSignal, 'timeout');
		vi.mocked(globalThis.fetch).mockResolvedValue(new Response('{}', { status: 200 }));

		await daemonFetch('/api/tools/traceroute', { method: 'POST' }, 35_000);

		expect(timeout).toHaveBeenCalledWith(35_000);
		timeout.mockRestore();
	});

	// NET-203: a 15 s DNS lookup on the G11 read "Daemon unreachable" while the daemon was still answering
	it('says NetTap took too long, not that it is unreachable, when its own time limit runs out', async () => {
		vi.mocked(globalThis.fetch).mockRejectedValue(new DOMException('The operation was aborted due to timeout', 'TimeoutError'));

		const result = await daemonFetch('/api/test');
		const body = await result.json();

		expect(result.status).toBe(502);
		expect(body.error).toBe('NetTap took too long to answer. Try again.');
		expect(body.error).not.toContain('unreachable');
		// the answer never reached the web server, so a save behind it is still unconfirmed
		expect(body.daemonAvailable).toBe(false);
	});

	// NET-229 (B-p): the reason (host:port, errno) goes to the web log, never into the reply
	it('returns 502 Response on connection error, with the reason only in the log', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => {});
		vi.mocked(globalThis.fetch).mockRejectedValue(new Error('connect ECONNREFUSED 172.18.0.1:8880'));

		const result = await daemonFetch('/api/test');
		const body = await result.json();

		expect(result.status).toBe(502);
		expect(body.error).toBe('Daemon unreachable');
		expect(JSON.stringify(body)).not.toContain('ECONNREFUSED');
		expect(log).toHaveBeenCalledWith(expect.stringContaining('ECONNREFUSED 172.18.0.1:8880'));
		expect(body.daemonAvailable).toBe(false);
		log.mockRestore();
	});

	// Review L5: Live and the shell poll every few seconds; a down daemon is logged once, not per call
	it('logs a down daemon once, then once when it answers again', async () => {
		vi.resetModules();
		const fresh = await import('./daemon');
		const error = vi.spyOn(console, 'error').mockImplementation(() => {});
		const info = vi.spyOn(console, 'info').mockImplementation(() => {});
		// the token file may also be reported; count only the reachability lines
		const downLines = () => error.mock.calls.filter(([line]) => String(line).startsWith('Daemon unreachable')).length;
		vi.mocked(globalThis.fetch).mockRejectedValue(new Error('connect ECONNREFUSED'));

		for (let i = 0; i < 3; i++) await fresh.daemonFetch('/api/live/stats');
		expect(downLines()).toBe(1);

		vi.mocked(globalThis.fetch).mockResolvedValue(new Response('{}', { status: 200 }));
		await fresh.daemonFetch('/api/live/stats');
		await fresh.daemonFetch('/api/live/stats');
		expect(info).toHaveBeenCalledTimes(1);

		vi.mocked(globalThis.fetch).mockRejectedValue(new Error('connect ECONNREFUSED'));
		await fresh.daemonFetch('/api/live/stats');
		expect(downLines()).toBe(2);
		error.mockRestore();
		info.mockRestore();
	});

	it("doesn't count a caller's own abort as the daemon going down", async () => {
		vi.resetModules();
		const fresh = await import('./daemon');
		const error = vi.spyOn(console, 'error').mockImplementation(() => {});
		const info = vi.spyOn(console, 'info').mockImplementation(() => {});
		const abort = Object.assign(new Error('This operation was aborted'), { name: 'AbortError' });

		for (let i = 0; i < 3; i++) {
			vi.mocked(globalThis.fetch).mockRejectedValueOnce(abort);
			await fresh.daemonFetch('/api/packets/download');
			vi.mocked(globalThis.fetch).mockResolvedValueOnce(new Response('{}', { status: 200 }));
			await fresh.daemonFetch('/api/system/ping');
		}
		expect(error.mock.calls.filter(([line]) => String(line).startsWith('Daemon unreachable'))).toHaveLength(0);
		expect(info).not.toHaveBeenCalled();
		error.mockRestore();
		info.mockRestore();
	});

	it('returns 502 on unknown error type', async () => {
		vi.mocked(globalThis.fetch).mockRejectedValue('string error');

		const result = await daemonFetch('/api/test');
		const body = await result.json();

		expect(result.status).toBe(502);
		// OLD CODE: expect(body.error).toContain('Unknown error'); (NET-229: the reason is only logged now)
		expect(body.error).toBe('Daemon unreachable');
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

// The daemon answers a rule update or an ET Pro change by ~270 s; the proxy must outwait it (NET-191 slice 2)
// Pins the daemon-to-proxy timing contract (the daemon's 240 s lock wait is pinned in test_rules_lock.py)
describe('RULE_UPDATE_TIMEOUT_MS', () => {
	it('is 290 s', () => {
		expect(RULE_UPDATE_TIMEOUT_MS).toBe(290_000);
	});
});
