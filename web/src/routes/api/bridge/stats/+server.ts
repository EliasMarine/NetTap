import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/bridge/stats
 * Proxies to the daemon's GET /api/bridge/stats endpoint.
 * Returns aggregated bridge statistics.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/bridge/stats');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
