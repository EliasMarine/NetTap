import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

// The daemon gives whois up to 15 s; the 10 s default cut a slow answer off as "unreachable"
const WHOIS_TIMEOUT_MS = 25_000;

/**
 * GET /api/lookup/whois/[ip]
 * Proxies to the daemon's GET /api/lookup/whois/{ip} endpoint.
 */
export const GET: RequestHandler = async ({ params }) => {
	const ip = encodeURIComponent(params.ip);
	// OLD CODE START — PR 2 (reliability): the 10 s default, below the daemon's own 15 s
	// const res = await daemonFetch(`/api/lookup/whois/${ip}`);
	// OLD CODE END
	const res = await daemonFetch(`/api/lookup/whois/${ip}`, undefined, WHOIS_TIMEOUT_MS);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
