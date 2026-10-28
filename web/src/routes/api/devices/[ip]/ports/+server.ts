import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/devices/{ip}/ports?from=&to=
 * Proxies to the daemon's GET /api/devices/{ip}/ports endpoint,
 * forwarding time range query parameters for device port analysis.
 */
export const GET: RequestHandler = async ({ url, params }) => {
	const queryParams = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	if (from) queryParams.set('from', from);
	if (to) queryParams.set('to', to);

	const query = queryParams.toString() ? `?${queryParams.toString()}` : '';
	const res = await daemonFetch(`/api/devices/${encodeURIComponent(params.ip)}/ports${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
