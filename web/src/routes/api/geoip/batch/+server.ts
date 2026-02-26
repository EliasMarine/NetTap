import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/geoip/batch?ips=1.1.1.1,8.8.8.8
 * Proxies to the daemon's GET /api/geoip/batch endpoint,
 * forwarding the ips query parameter.
 */
export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	const ips = url.searchParams.get('ips');
	if (ips) params.set('ips', ips);

	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/geoip/batch${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
