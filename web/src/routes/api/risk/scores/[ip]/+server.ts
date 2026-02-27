import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/risk/scores/:ip
 * Proxies to the daemon's GET /api/risk/scores/:ip endpoint.
 * Returns the risk score for a single device by IP address.
 */
export const GET: RequestHandler = async ({ params }) => {
	const ip = params.ip;
	const res = await daemonFetch(`/api/risk/scores/${encodeURIComponent(ip)}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
