import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/cyberchef/url
 * Proxies the request body to the daemon's POST /api/cyberchef/url endpoint.
 * Expects JSON body with { recipe_fragment, input_data }.
 */
export const POST: RequestHandler = async ({ request }) => {
	let body: Record<string, unknown>;
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON request body.' }, { status: 400 });
	}

	const res = await daemonFetch('/api/cyberchef/url', {
		method: 'POST',
		body: JSON.stringify(body),
	});

	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
