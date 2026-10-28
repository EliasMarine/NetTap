import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/tools/mac-lookup/[mac]
 * Proxies to the daemon's GET /api/tools/mac-lookup/{mac} endpoint.
 */
export const GET: RequestHandler = async ({ params }) => {
	const mac = encodeURIComponent(params.mac);
	const res = await daemonFetch(`/api/tools/mac-lookup/${mac}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
