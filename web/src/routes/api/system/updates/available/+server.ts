import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/system/updates/available
 * Proxies to the daemon's GET /api/system/updates/available endpoint.
 * Returns a list of available updates that have been previously checked.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/system/updates/available');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
