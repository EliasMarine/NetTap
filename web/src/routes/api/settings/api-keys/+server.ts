import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/settings/api-keys
 * Proxies to the daemon's GET /api/settings/api-keys endpoint.
 * Returns which API keys are configured (boolean flags only).
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/settings/api-keys');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * POST /api/settings/api-keys
 * Proxies to the daemon's POST /api/settings/api-keys endpoint.
 * Saves API key values to the environment file.
 */
export const POST: RequestHandler = async ({ request }) => {
	let body: Record<string, unknown> = {};
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	const res = await daemonFetch('/api/settings/api-keys', {
		method: 'POST',
		body: JSON.stringify(body),
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
