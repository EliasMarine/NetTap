import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/threats/dns-anomalies?from=&to=
 * Proxies to the daemon's GET /api/threats/dns-anomalies endpoint.
 * Returns DNS anomaly analysis (DGA suspects, tunneling, NXDOMAIN spikes, suspicious TLDs).
 */
export const GET: RequestHandler = async ({ url }) => {
	const qs = new URLSearchParams();
	for (const [k, v] of url.searchParams) qs.set(k, v);
	const query = qs.toString() ? `?${qs.toString()}` : '';
	const res = await daemonFetch(`/api/threats/dns-anomalies${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
