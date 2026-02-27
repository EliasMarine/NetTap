import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/internet/stats
 * Proxies to the daemon's GET /api/internet/stats endpoint.
 * Returns aggregated internet health statistics.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/internet/stats');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
