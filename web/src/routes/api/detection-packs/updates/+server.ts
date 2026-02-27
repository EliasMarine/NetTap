import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/detection-packs/updates
 * Proxies to the daemon's GET /api/detection-packs/updates endpoint.
 * Returns available updates for installed detection packs.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/detection-packs/updates');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
