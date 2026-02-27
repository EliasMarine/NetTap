import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/investigations/stats
 * Proxies to the daemon's GET /api/investigations/stats endpoint.
 * Returns investigation statistics aggregated by status and severity.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/investigations/stats');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
