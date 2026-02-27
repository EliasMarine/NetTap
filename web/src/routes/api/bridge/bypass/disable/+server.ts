import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/bridge/bypass/disable
 * Proxies to the daemon's POST /api/bridge/bypass/disable endpoint.
 * Disables bypass mode (resumes normal bridge capture).
 */
export const POST: RequestHandler = async () => {
	const res = await daemonFetch('/api/bridge/bypass/disable', {
		method: 'POST',
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
