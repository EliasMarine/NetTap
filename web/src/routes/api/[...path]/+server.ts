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

// tshark-backed previews run up to 45 s in the daemon; the default is 10 s.
// OLD CODE START — NET-154: the certificate overview's 50 s budget needs the same allowance
// const SLOW_PATH_TIMEOUT_MS: Record<string, number> = { '/api/pcap/preview': 60_000 };
// OLD CODE END
// The certificate overview stops itself at 50 s and answers 503, so 60 s always gets its reason
// OLD CODE START — NET-188: packet analysis needs its own allowances
// const SLOW_PATH_TIMEOUT_MS: Record<string, number> = {
// 	'/api/pcap/preview': 60_000,
// 	// Filtered (?site=&server=) requests too: the lookup is by path
// 	'/api/certificates/overview': 60_000,
// };
// OLD CODE END
const SLOW_PATH_TIMEOUT_MS: Record<string, number> = {
	'/api/pcap/preview': 60_000,
	// Filtered (?site=&server=) requests too: the lookup is by path
	'/api/certificates/overview': 60_000,
	// NET-188: a packet search or one packet's detail stops itself at ~48 s, so 55 s gets its reason
	'/api/packets/search': 55_000,
	'/api/packets/packet': 55_000,
	// Listing captures, suggesting fields and checking a filter each run a short tshark job
	'/api/packets/captures': 15_000,
	'/api/packets/fields': 15_000,
	'/api/packets/check-filter': 15_000,
};
// NET-160: the address, domain and Suricata category pages stop themselves at 25 s and answer 503, so 30 s gets the reason
const SLOW_PREFIX_TIMEOUT_MS: [string, number][] = [
	['/api/addresses/', 30_000],
	['/api/domains/', 30_000],
	['/api/alerts/suricata/', 30_000],
];

function timeoutFor(path: string): number | undefined {
	return SLOW_PATH_TIMEOUT_MS[path] ?? SLOW_PREFIX_TIMEOUT_MS.find(([prefix]) => path.startsWith(prefix))?.[1];
}

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

	// PCAP downloads (0.8-3.5 GB files, or a filtered merge first) last as long as the
	// browser keeps reading: a fixed 10 s timeout cut them off mid-file.
	// OLD CODE START — NET-188: saved capture files on the Packets page download the same way
	// if (path.startsWith('/api/pcap/download')) {
	// OLD CODE END
	if (path.startsWith('/api/pcap/download') || path === '/api/packets/capture-file') {
		options.signal = request.signal;
	}

	// OLD CODE START — 2026-11-02: one 10 s timeout for every path, downloads included
	// const res = await daemonFetch(daemonPath, options);
	// OLD CODE END
	// OLD CODE START — NET-160: exact paths only
	// const res = await daemonFetch(daemonPath, options, SLOW_PATH_TIMEOUT_MS[path]);
	// OLD CODE END
	const res = await daemonFetch(daemonPath, options, timeoutFor(path));

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
