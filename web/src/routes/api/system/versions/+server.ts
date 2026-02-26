import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/system/versions
 * Proxies to the daemon's GET /api/system/versions endpoint.
 * Returns all component versions installed on the appliance.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/system/versions');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
