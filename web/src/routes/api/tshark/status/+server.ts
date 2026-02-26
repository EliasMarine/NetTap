import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/tshark/status
 * Proxies to the daemon's GET /api/tshark/status endpoint.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/tshark/status');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
