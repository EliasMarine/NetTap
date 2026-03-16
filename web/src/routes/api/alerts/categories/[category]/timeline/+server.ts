import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/alerts/categories/:category/timeline?from=&to=&interval=1h
 * Proxies to the daemon's alert category timeline endpoint.
 * Returns time-series data for the category broken down by sub-categories.
 */
export const GET: RequestHandler = async ({ url, params }) => {
	const qs = new URLSearchParams();
	for (const [k, v] of url.searchParams) qs.set(k, v);
	const query = qs.toString() ? `?${qs.toString()}` : '';
	const category = encodeURIComponent(params.category);
	const res = await daemonFetch(`/api/alerts/categories/${category}/timeline${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
