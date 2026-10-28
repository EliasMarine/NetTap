import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/suricata/rules/schedule
 * Proxies to the daemon's GET /api/suricata/rules/schedule endpoint.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/suricata/rules/schedule');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * PUT /api/suricata/rules/schedule
 * Proxies to the daemon's PUT /api/suricata/rules/schedule endpoint.
 */
export const PUT: RequestHandler = async ({ request }) => {
	const body = await request.text();
	const res = await daemonFetch('/api/suricata/rules/schedule', {
		method: 'PUT',
		body,
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
