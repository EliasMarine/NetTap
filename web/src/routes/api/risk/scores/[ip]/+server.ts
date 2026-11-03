import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/risk/scores/:ip
 * Proxies to the daemon's GET /api/risk/scores/:ip endpoint.
 * Returns the risk score for a single device by IP address.
 */
export const GET: RequestHandler = async ({ params, url }) => {
	const ip = params.ip;
	// OLD CODE START — dropped from/to, so a time range picked on the page never reached the daemon
	// const res = await daemonFetch(`/api/risk/scores/${encodeURIComponent(ip)}`);
	// OLD CODE END
	const query = new URLSearchParams();
	for (const key of ['from', 'to']) {
		const value = url.searchParams.get(key);
		if (value) query.set(key, value);
	}
	const qs = query.toString() ? `?${query.toString()}` : '';
	const res = await daemonFetch(`/api/risk/scores/${encodeURIComponent(ip)}${qs}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
