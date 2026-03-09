import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/suricata/rules/stats
 * Proxies to the daemon's GET /api/suricata/rules/stats endpoint.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/suricata/rules/stats');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
