import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/system/updates/apply
 * Proxies to the daemon's POST /api/system/updates/apply endpoint.
 * Applies updates to the specified components.
 * Expects JSON body: { components: string[] }
 */
export const POST: RequestHandler = async ({ request }) => {
	let body: { components: string[] };

	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	if (!body.components || !Array.isArray(body.components) || body.components.length === 0) {
		return json({ error: 'components array is required and must not be empty' }, { status: 400 });
	}

	const res = await daemonFetch('/api/system/updates/apply', {
		method: 'POST',
		body: JSON.stringify({ components: body.components }),
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
