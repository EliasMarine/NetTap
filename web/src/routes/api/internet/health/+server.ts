import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/internet/health
 * Proxies to the daemon's GET /api/internet/health endpoint.
 * Returns the most recent internet health check result.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/internet/health');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
