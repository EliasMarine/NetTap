import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Tests for the catch-all API proxy route at /api/[...path].
 *
 * We re-implement the proxy logic here to test it in isolation
 * (the actual +server.ts depends on SvelteKit imports).
 */

// Mock daemonFetch
const mockDaemonFetch = vi.fn();

async function proxyToDaemon(
	{ url, request }: { url: URL; request: Request },
	method: string
): Promise<Response> {
	const path = url.pathname;
	const query = url.search;
	const daemonPath = `${path}${query}`;

	const options: RequestInit = { method };

	if (method !== 'GET' && method !== 'HEAD') {
		const body = await request.text();
		if (body) {
			options.body = body;
			options.headers = { 'Content-Type': request.headers.get('content-type') || 'application/json' };
		}
	}

	const res = await mockDaemonFetch(daemonPath, options);

	const contentType = res.headers.get('content-type') || 'application/json';
	if (contentType.includes('application/octet-stream') || contentType.includes('application/vnd.tcpdump.pcap')) {
		return new Response(res.body, {
			status: res.status,
			headers: {
				'Content-Type': contentType,
				'Content-Disposition': res.headers.get('content-disposition') || '',
			},
		});
	}

	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return new Response(JSON.stringify(data), {
		status: res.status,
		headers: { 'Content-Type': 'application/json' },
	});
}

beforeEach(() => {
	mockDaemonFetch.mockReset();
});

describe('catch-all API proxy', () => {
	it('forwards GET requests with query params to daemon', async () => {
		const mockResponse = new Response(JSON.stringify({ connections: [], count: 0 }), {
			status: 200,
			headers: { 'Content-Type': 'application/json' },
		});
		mockDaemonFetch.mockResolvedValue(mockResponse);

		const url = new URL('http://localhost/api/live/connections?device=192.168.1.1&limit=50');
		const request = new Request(url, { method: 'GET' });

		await proxyToDaemon({ url, request }, 'GET');

		expect(mockDaemonFetch).toHaveBeenCalledWith(
			'/api/live/connections?device=192.168.1.1&limit=50',
			{ method: 'GET' }
		);
	});

	it('forwards POST requests with JSON body', async () => {
		const mockResponse = new Response(JSON.stringify({ mac: 'aa:bb:cc:dd:ee:ff', is_iot: true }), {
			status: 200,
			headers: { 'Content-Type': 'application/json' },
		});
		mockDaemonFetch.mockResolvedValue(mockResponse);

		const url = new URL('http://localhost/api/iot/devices/aa%3Abb%3Acc%3Add%3Aee%3Aff/classify');
		const request = new Request(url, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ manufacturer: 'Ring' }),
		});

		await proxyToDaemon({ url, request }, 'POST');

		expect(mockDaemonFetch).toHaveBeenCalledWith(
			'/api/iot/devices/aa%3Abb%3Acc%3Add%3Aee%3Aff/classify',
			expect.objectContaining({
				method: 'POST',
				body: '{"manufacturer":"Ring"}',
			})
		);
	});

	it('forwards PUT requests for settings', async () => {
		const mockResponse = new Response(JSON.stringify({ result: 'ok' }), {
			status: 200,
			headers: { 'Content-Type': 'application/json' },
		});
		mockDaemonFetch.mockResolvedValue(mockResponse);

		const url = new URL('http://localhost/api/settings/bandwidth-cap');
		const request = new Request(url, {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ monthly_cap_gb: 500 }),
		});

		await proxyToDaemon({ url, request }, 'PUT');

		expect(mockDaemonFetch).toHaveBeenCalledWith(
			'/api/settings/bandwidth-cap',
			expect.objectContaining({
				method: 'PUT',
				body: '{"monthly_cap_gb":500}',
			})
		);
	});

	it('returns daemon JSON response with correct status', async () => {
		const data = { domains: [{ domain: 'google.com', count: 42 }] };
		const mockResponse = new Response(JSON.stringify(data), {
			status: 200,
			headers: { 'Content-Type': 'application/json' },
		});
		mockDaemonFetch.mockResolvedValue(mockResponse);

		const url = new URL('http://localhost/api/dns/top-domains?from=2026-03-09T00:00:00Z');
		const request = new Request(url, { method: 'GET' });

		const result = await proxyToDaemon({ url, request }, 'GET');
		const body = await result.json();

		expect(result.status).toBe(200);
		expect(body.domains).toHaveLength(1);
		expect(body.domains[0].domain).toBe('google.com');
	});

	it('passes through daemon error status codes', async () => {
		const mockResponse = new Response(JSON.stringify({ error: 'Not found' }), {
			status: 404,
			headers: { 'Content-Type': 'application/json' },
		});
		mockDaemonFetch.mockResolvedValue(mockResponse);

		const url = new URL('http://localhost/api/pcap/files');
		const request = new Request(url, { method: 'GET' });

		const result = await proxyToDaemon({ url, request }, 'GET');

		expect(result.status).toBe(404);
	});

	it('streams binary content for PCAP downloads', async () => {
		const pcapData = new Uint8Array([0xd4, 0xc3, 0xb2, 0xa1]); // PCAP magic bytes
		const mockResponse = new Response(pcapData, {
			status: 200,
			headers: {
				'Content-Type': 'application/vnd.tcpdump.pcap',
				'Content-Disposition': 'attachment; filename="capture.pcap"',
			},
		});
		mockDaemonFetch.mockResolvedValue(mockResponse);

		const url = new URL('http://localhost/api/pcap/download?filter=tcp+port+80');
		const request = new Request(url, { method: 'GET' });

		const result = await proxyToDaemon({ url, request }, 'GET');

		expect(result.headers.get('Content-Type')).toBe('application/vnd.tcpdump.pcap');
		expect(result.headers.get('Content-Disposition')).toBe('attachment; filename="capture.pcap"');
	});

	it('handles daemon unreachable (502 response)', async () => {
		const mockResponse = new Response(
			JSON.stringify({ error: 'Daemon unreachable: fetch failed', daemonAvailable: false }),
			{ status: 502, headers: { 'Content-Type': 'application/json' } }
		);
		mockDaemonFetch.mockResolvedValue(mockResponse);

		const url = new URL('http://localhost/api/bandwidth/monthly');
		const request = new Request(url, { method: 'GET' });

		const result = await proxyToDaemon({ url, request }, 'GET');
		const body = await result.json();

		expect(result.status).toBe(502);
		expect(body.daemonAvailable).toBe(false);
	});

	it('handles non-JSON daemon responses gracefully', async () => {
		const mockResponse = new Response('Internal Server Error', {
			status: 500,
			headers: { 'Content-Type': 'text/plain' },
		});
		mockDaemonFetch.mockResolvedValue(mockResponse);

		const url = new URL('http://localhost/api/changelog');
		const request = new Request(url, { method: 'GET' });

		const result = await proxyToDaemon({ url, request }, 'GET');
		const body = await result.json();

		expect(result.status).toBe(500);
		expect(body.error).toBe('Failed to parse daemon response');
	});
});
