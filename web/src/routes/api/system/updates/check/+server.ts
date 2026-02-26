import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/system/updates/check
 * Proxies to the daemon's POST /api/system/updates/check endpoint.
 * Checks for new updates from upstream sources.
 */
export const POST: RequestHandler = async () => {
	const res = await daemonFetch('/api/system/updates/check', {
		method: 'POST',
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
