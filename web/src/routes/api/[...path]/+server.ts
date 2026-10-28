import { json } from '@sveltejs/kit';
import type { RequestEvent } from '@sveltejs/kit';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * Catch-all proxy for /api/* routes not handled by more specific route files.
 * Forwards requests to the daemon at http://nettap-storage-daemon:8880.
 *
 * SvelteKit routing gives priority to explicit routes (e.g. /api/traffic/summary)
 * over this catch-all, so existing handlers are unaffected.
 *
 * Covers: /api/live/*, /api/bandwidth/*, /api/dns/*, /api/iot/*,
 *         /api/lan/*, /api/pcap/*, /api/changelog/*, /api/certificates/*,
 *         /api/settings/bandwidth-cap, and any future daemon endpoints.
 */

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

	const res = await daemonFetch(daemonPath, options);

	// For download endpoints, stream the response through
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
	return json(data, { status: res.status });
}

export const GET = async (event: RequestEvent) => proxyToDaemon(event, 'GET');
export const POST = async (event: RequestEvent) => proxyToDaemon(event, 'POST');
export const PUT = async (event: RequestEvent) => proxyToDaemon(event, 'PUT');
export const DELETE = async (event: RequestEvent) => proxyToDaemon(event, 'DELETE');
