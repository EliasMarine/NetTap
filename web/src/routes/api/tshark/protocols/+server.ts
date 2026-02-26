import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/tshark/protocols
 * Proxies to the daemon's GET /api/tshark/protocols endpoint.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/tshark/protocols');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
