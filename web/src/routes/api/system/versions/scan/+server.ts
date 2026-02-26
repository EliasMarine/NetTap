import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/system/versions/scan
 * Proxies to the daemon's POST /api/system/versions/scan endpoint.
 * Triggers a fresh scan of all component versions.
 */
export const POST: RequestHandler = async () => {
	const res = await daemonFetch('/api/system/versions/scan', {
		method: 'POST',
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
