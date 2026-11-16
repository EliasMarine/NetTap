import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch, UPDATE_CHECK_TIMEOUT_MS } from '$lib/server/daemon.js';

/**
 * POST /api/system/updates/check
 * Proxies to the daemon's POST /api/system/updates/check endpoint.
 * Checks for new updates from upstream sources.
 */
export const POST: RequestHandler = async () => {
	// OLD CODE: const res = await daemonFetch('/api/system/updates/check', { method: 'POST' }); (the 10 s default)
	const res = await daemonFetch('/api/system/updates/check', { method: 'POST' }, UPDATE_CHECK_TIMEOUT_MS);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
