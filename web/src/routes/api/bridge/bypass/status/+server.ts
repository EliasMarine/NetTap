import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/bridge/bypass/status
 * Proxies to the daemon's GET /api/bridge/bypass/status endpoint.
 * Returns the current bypass mode status.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/bridge/bypass/status');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
