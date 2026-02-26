import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/investigations/:id/devices
 * Proxies to the daemon's POST /api/investigations/:id/devices endpoint.
 * Links a device IP to an investigation.
 */
export const POST: RequestHandler = async ({ params, request }) => {
	const id = params.id;
	let body: Record<string, unknown> = {};
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	const res = await daemonFetch(`/api/investigations/${encodeURIComponent(id)}/devices`, {
		method: 'POST',
		body: JSON.stringify(body),
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
