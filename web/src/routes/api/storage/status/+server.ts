import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/storage/status
 * Proxies to the daemon's GET /api/storage/status endpoint.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/storage/status');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
