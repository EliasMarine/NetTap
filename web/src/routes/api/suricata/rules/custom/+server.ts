import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/suricata/rules/custom
 * Proxies to the daemon's GET /api/suricata/rules/custom endpoint.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/suricata/rules/custom');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * POST /api/suricata/rules/custom
 * Proxies to the daemon's POST /api/suricata/rules/custom endpoint.
 */
export const POST: RequestHandler = async ({ request }) => {
	const body = await request.text();
	const res = await daemonFetch('/api/suricata/rules/custom', {
		method: 'POST',
		body,
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
