import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/detection-packs/:id/enable
 * Proxies to the daemon's POST /api/detection-packs/:id/enable endpoint.
 * Enables a detection pack (activates its rules).
 */
export const POST: RequestHandler = async ({ params }) => {
	const packId = params.id;
	const res = await daemonFetch(`/api/detection-packs/${encodeURIComponent(packId)}/enable`, {
		method: 'POST',
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
