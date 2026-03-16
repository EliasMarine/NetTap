import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/alerts/suppress
 * Proxies to the daemon's POST /api/alerts/suppress endpoint.
 * Suppresses a specific alert signature (optionally scoped to a device IP).
 * Body: { signature_id: number, device_ip?: string, reason?: string }
 */
export const POST: RequestHandler = async ({ request }) => {
	const body = await request.json();
	const res = await daemonFetch('/api/alerts/suppress', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
