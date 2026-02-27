import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/detection-packs/stats
 * Proxies to the daemon's GET /api/detection-packs/stats endpoint.
 * Returns aggregate pack statistics (total, enabled, total_rules).
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/detection-packs/stats');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
