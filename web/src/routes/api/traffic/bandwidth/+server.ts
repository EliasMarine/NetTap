import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/traffic/bandwidth?from=&to=&interval=5m
 * Proxies to the daemon's GET /api/traffic/bandwidth endpoint,
 * forwarding from/to/interval query parameters.
 */
export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	const interval = url.searchParams.get('interval');
	if (from) params.set('from', from);
	if (to) params.set('to', to);
	if (interval) params.set('interval', interval);

	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/traffic/bandwidth${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
