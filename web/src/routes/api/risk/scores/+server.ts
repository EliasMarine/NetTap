import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/risk/scores
 * Proxies to the daemon's GET /api/risk/scores endpoint.
 * Returns risk scores for all monitored devices.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/risk/scores');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
