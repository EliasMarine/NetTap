import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/search
 * Proxies to the daemon's POST /api/search endpoint.
 * Accepts a JSON body with { query: string } for natural language search.
 */
export const POST: RequestHandler = async ({ request }) => {
	let body: Record<string, unknown> = {};
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	const res = await daemonFetch('/api/search', {
		method: 'POST',
		body: JSON.stringify(body),
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
