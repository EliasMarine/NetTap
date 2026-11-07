import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch, THREAT_SCAN_TIMEOUT_MS } from '$lib/server/daemon.js';

/**
 * GET /api/threats/beaconing?from=&to=
 * Proxies to the daemon's GET /api/threats/beaconing endpoint.
 * Returns beaconing detection results (periodic callback suspects).
 */
export const GET: RequestHandler = async ({ url }) => {
	const qs = new URLSearchParams();
	for (const [k, v] of url.searchParams) qs.set(k, v);
	const query = qs.toString() ? `?${qs.toString()}` : '';
	// OLD CODE: const res = await daemonFetch(`/api/threats/beaconing${query}`); (the 10 s default: /threats failed once the scan passed it)
	const res = await daemonFetch(`/api/threats/beaconing${query}`, undefined, THREAT_SCAN_TIMEOUT_MS);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
