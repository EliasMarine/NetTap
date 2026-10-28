import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/lookup/whois/[ip]
 * Proxies to the daemon's GET /api/lookup/whois/{ip} endpoint.
 */
export const GET: RequestHandler = async ({ params }) => {
	const ip = encodeURIComponent(params.ip);
	const res = await daemonFetch(`/api/lookup/whois/${ip}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
