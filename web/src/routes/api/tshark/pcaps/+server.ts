import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/tshark/pcaps
 * Proxies to the daemon's GET /api/tshark/pcaps endpoint.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/tshark/pcaps');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
