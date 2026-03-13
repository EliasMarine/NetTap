import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/alerts/false-positive
 * Proxies to the daemon's POST /api/alerts/false-positive endpoint.
 * Marks a signature as a false positive.
 * Body: { signature_id: number, reason?: string }
 */
export const POST: RequestHandler = async ({ request }) => {
	const body = await request.json();
	const res = await daemonFetch('/api/alerts/false-positive', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
