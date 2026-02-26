import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/devices/{ip}/connections?from=&to=&page=1&size=50
 * Proxies to the daemon's GET /api/devices/{ip}/connections endpoint,
 * forwarding all query parameters for paginated device connection listing.
 */
export const GET: RequestHandler = async ({ url, params }) => {
	const queryParams = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	const page = url.searchParams.get('page');
	const size = url.searchParams.get('size');
	if (from) queryParams.set('from', from);
	if (to) queryParams.set('to', to);
	if (page) queryParams.set('page', page);
	if (size) queryParams.set('size', size);

	const query = queryParams.toString() ? `?${queryParams.toString()}` : '';
	const res = await daemonFetch(`/api/devices/${encodeURIComponent(params.ip)}/connections${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
