import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/bridge/health
 * Proxies to the daemon's GET /api/bridge/health endpoint.
 * Returns the current bridge health snapshot.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/bridge/health');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
