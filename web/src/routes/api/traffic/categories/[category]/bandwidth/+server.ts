import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/traffic/categories/:category/bandwidth?from=&to=&interval=
 * Proxies to the daemon's category bandwidth endpoint.
 */
export const GET: RequestHandler = async ({ url, params }) => {
	const qs = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	const interval = url.searchParams.get('interval');
	if (from) qs.set('from', from);
	if (to) qs.set('to', to);
	if (interval) qs.set('interval', interval);

	const query = qs.toString() ? `?${qs.toString()}` : '';
	const category = encodeURIComponent(params.category);
	const res = await daemonFetch(`/api/traffic/categories/${category}/bandwidth${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
