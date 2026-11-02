import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/risk/scores
 * Proxies to the daemon's GET /api/risk/scores endpoint.
 * Returns risk scores for all monitored devices.
 */
export const GET: RequestHandler = async ({ url }) => {
	// OLD CODE START — dropped the query, so from/to/limit never reached the daemon
	// const res = await daemonFetch('/api/risk/scores');
	// OLD CODE END
	const params = new URLSearchParams();
	for (const key of ['from', 'to', 'limit']) {
		const value = url.searchParams.get(key);
		if (value) params.set(key, value);
	}
	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/risk/scores${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
