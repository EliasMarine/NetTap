import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/geoip/[ip]
 * Proxies to the daemon's GET /api/geoip/{ip} endpoint,
 * forwarding the IP address path parameter.
 */
export const GET: RequestHandler = async ({ params }) => {
	const ip = encodeURIComponent(params.ip);
	const res = await daemonFetch(`/api/geoip/${ip}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
