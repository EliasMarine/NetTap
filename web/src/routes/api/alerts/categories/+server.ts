import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/alerts/categories?from=&to=
 * Proxies to the daemon's enhanced alert categories endpoint.
 * Returns categories with severity breakdowns, trends, sparklines, and sub-categories.
 */
export const GET: RequestHandler = async ({ url }) => {
	const qs = new URLSearchParams();
	for (const [k, v] of url.searchParams) qs.set(k, v);
	const query = qs.toString() ? `?${qs.toString()}` : '';
	const res = await daemonFetch(`/api/alerts/categories${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
