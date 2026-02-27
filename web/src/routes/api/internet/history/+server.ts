import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/internet/history?limit=100
 * Proxies to the daemon's GET /api/internet/history endpoint.
 * Returns historical internet health check results.
 */
export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	const limit = url.searchParams.get('limit');
	if (limit) params.set('limit', limit);

	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/internet/history${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
