import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/alerts/top-ips?from=&to=&limit=&direction=src|dest
 * Proxies to the daemon's top IPs aggregation endpoint.
 */
export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	for (const key of ['from', 'to', 'limit', 'direction']) {
		const val = url.searchParams.get(key);
		if (val) params.set(key, val);
	}

	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/alerts/top-ips${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
