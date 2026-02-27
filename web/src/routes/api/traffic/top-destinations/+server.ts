import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/traffic/top-destinations?from=&to=&limit=20
 * Proxies to the daemon's GET /api/traffic/top-destinations endpoint,
 * forwarding from/to/limit query parameters.
 */
export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	const limit = url.searchParams.get('limit');
	if (from) params.set('from', from);
	if (to) params.set('to', to);
	if (limit) params.set('limit', limit);

	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/traffic/top-destinations${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
