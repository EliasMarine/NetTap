import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/cyberchef/status
 * Proxies to the daemon's GET /api/cyberchef/status endpoint.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/cyberchef/status');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
