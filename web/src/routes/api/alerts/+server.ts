import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/alerts?from=&to=&severity=&page=1&size=50
 * Proxies to the daemon's GET /api/alerts endpoint,
 * forwarding all query parameters for paginated alert listing.
 */
export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	const severity = url.searchParams.get('severity');
	const page = url.searchParams.get('page');
	const size = url.searchParams.get('size');
	if (from) params.set('from', from);
	if (to) params.set('to', to);
	if (severity) params.set('severity', severity);
	if (page) params.set('page', page);
	if (size) params.set('size', size);

	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/alerts${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
