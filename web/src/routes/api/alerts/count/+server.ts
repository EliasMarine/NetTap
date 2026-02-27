import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/alerts/count?from=&to=
 * Proxies to the daemon's GET /api/alerts/count endpoint.
 * Returns total alert count with severity breakdown.
 */
export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	if (from) params.set('from', from);
	if (to) params.set('to', to);

	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/alerts/count${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
