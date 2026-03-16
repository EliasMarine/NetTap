import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/threats/intel?from=&to=
 * Proxies to the daemon's GET /api/threats/intel endpoint.
 * Populates threat intelligence from Suricata data and returns indicator matches.
 */
export const GET: RequestHandler = async ({ url }) => {
	const qs = new URLSearchParams();
	for (const [k, v] of url.searchParams) qs.set(k, v);
	const query = qs.toString() ? `?${qs.toString()}` : '';
	const res = await daemonFetch(`/api/threats/intel${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
