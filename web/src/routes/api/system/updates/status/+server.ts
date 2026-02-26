import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/system/updates/status
 * Proxies to the daemon's GET /api/system/updates/status endpoint.
 * Returns the current status of an in-progress or completed update operation.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/system/updates/status');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
