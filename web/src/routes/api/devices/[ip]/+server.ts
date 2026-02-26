import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/devices/{ip}?from=&to=
 * Proxies to the daemon's GET /api/devices/{ip} endpoint,
 * forwarding time range query parameters for single device detail.
 */
export const GET: RequestHandler = async ({ url, params }) => {
	const queryParams = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	if (from) queryParams.set('from', from);
	if (to) queryParams.set('to', to);

	const query = queryParams.toString() ? `?${queryParams.toString()}` : '';
	const res = await daemonFetch(`/api/devices/${encodeURIComponent(params.ip)}${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
