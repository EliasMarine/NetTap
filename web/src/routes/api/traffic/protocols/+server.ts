import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/traffic/protocols?from=&to=
 * Proxies to the daemon's GET /api/traffic/protocols endpoint,
 * forwarding from/to time range query parameters.
 */
export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	if (from) params.set('from', from);
	if (to) params.set('to', to);

	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/traffic/protocols${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
