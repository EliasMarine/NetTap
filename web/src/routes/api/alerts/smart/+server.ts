import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/alerts/smart?from=&to=&device_ip=&include_info=false&limit=50
 * Proxies to the daemon's GET /api/alerts/smart endpoint.
 * Returns grouped, deduplicated, severity-ranked smart alerts.
 */
export const GET: RequestHandler = async ({ url }) => {
	const qs = new URLSearchParams();
	for (const [k, v] of url.searchParams) qs.set(k, v);
	const query = qs.toString() ? `?${qs.toString()}` : '';
	const res = await daemonFetch(`/api/alerts/smart${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
