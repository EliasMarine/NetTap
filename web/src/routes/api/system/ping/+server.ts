import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/system/ping
 * Proxies to the daemon's liveness check (GET /api/health, {status: 'ok'}).
 * The top bar polls this; /api/system/health also reads disks, SMART and OpenSearch.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/health', undefined, 5_000);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
