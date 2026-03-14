import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/threats/report?from=&to=
 * Proxies to the daemon's GET /api/threats/report endpoint.
 * Returns the unified threat report (summary, kill chains, beaconing, DNS, lateral, investigations).
 */
export const GET: RequestHandler = async ({ url }) => {
	const qs = new URLSearchParams();
	for (const [k, v] of url.searchParams) qs.set(k, v);
	const query = qs.toString() ? `?${qs.toString()}` : '';
	const res = await daemonFetch(`/api/threats/report${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
