import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/system/updates/rollback
 * Proxies to the daemon's POST /api/system/updates/rollback endpoint.
 * Rolls back a specific component to its previous version.
 * Expects JSON body: { component: string }
 */
export const POST: RequestHandler = async ({ request }) => {
	let body: { component: string };

	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	// OLD CODE: if (!body.component || typeof body.component !== 'string') { (NET-291 review: the JSON body `null` threw here as a 500)
	if (!body || typeof body !== 'object' || !body.component || typeof body.component !== 'string') {
		return json({ error: 'component is required and must be a string' }, { status: 400 });
	}

	const res = await daemonFetch('/api/system/updates/rollback', {
		method: 'POST',
		body: JSON.stringify({ component: body.component }),
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
