import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/bridge/bypass/enable
 * Proxies to the daemon's POST /api/bridge/bypass/enable endpoint.
 * Enables bypass mode (stops capture, passes traffic through directly).
 */
export const POST: RequestHandler = async () => {
	const res = await daemonFetch('/api/bridge/bypass/enable', {
		method: 'POST',
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
