import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/suricata/rules/update
 * Proxies to the daemon's POST /api/suricata/rules/update endpoint.
 */
export const POST: RequestHandler = async () => {
	const res = await daemonFetch('/api/suricata/rules/update', { method: 'POST' });
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
