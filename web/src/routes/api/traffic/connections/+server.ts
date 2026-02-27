import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/traffic/connections?from=&to=&page=1&size=50&q=
 * Proxies to the daemon's GET /api/traffic/connections endpoint,
 * forwarding all query parameters for paginated connection listing.
 */
export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	const page = url.searchParams.get('page');
	const size = url.searchParams.get('size');
	const q = url.searchParams.get('q');
	if (from) params.set('from', from);
	if (to) params.set('to', to);
	if (page) params.set('page', page);
	if (size) params.set('size', size);
	if (q) params.set('q', q);

	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/traffic/connections${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
