import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/internet/check
 * Proxies to the daemon's POST /api/internet/check endpoint.
 * Triggers an on-demand internet health check and returns the result.
 */
export const POST: RequestHandler = async () => {
	const res = await daemonFetch('/api/internet/check', {
		method: 'POST',
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
