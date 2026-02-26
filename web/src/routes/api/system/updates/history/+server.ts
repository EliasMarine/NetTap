import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/system/updates/history
 * Proxies to the daemon's GET /api/system/updates/history endpoint.
 * Returns the history of past update operations.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/system/updates/history');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
