import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/devices?from=&to=&sort=bytes&order=desc&limit=100
 * Proxies to the daemon's GET /api/devices endpoint,
 * forwarding all query parameters for the device inventory listing.
 */
export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	const sort = url.searchParams.get('sort');
	const order = url.searchParams.get('order');
	const limit = url.searchParams.get('limit');
	if (from) params.set('from', from);
	if (to) params.set('to', to);
	if (sort) params.set('sort', sort);
	if (order) params.set('order', order);
	if (limit) params.set('limit', limit);

	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/devices${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
