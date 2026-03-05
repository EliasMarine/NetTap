import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/settings/excluded-ips
 * Returns the list of IPs excluded from device-centric views.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/settings/excluded-ips');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * PUT /api/settings/excluded-ips
 * Replace the excluded IP list.
 * Body: { "excluded_ips": ["99.10.70.92", "192.168.1.1"] }
 */
export const PUT: RequestHandler = async ({ request }) => {
	let body: Record<string, unknown> = {};
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	const res = await daemonFetch('/api/settings/excluded-ips', {
		method: 'PUT',
		body: JSON.stringify(body),
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
