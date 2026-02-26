import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/detection-packs/:id/disable
 * Proxies to the daemon's POST /api/detection-packs/:id/disable endpoint.
 * Disables a detection pack (deactivates its rules).
 */
export const POST: RequestHandler = async ({ params }) => {
	const packId = params.id;
	const res = await daemonFetch(`/api/detection-packs/${encodeURIComponent(packId)}/disable`, {
		method: 'POST',
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
