import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/detection-packs/:id/install
 * Proxies to the daemon's POST /api/detection-packs/:id/install endpoint.
 * Installs a detection pack from the community registry.
 */
export const POST: RequestHandler = async ({ params }) => {
	const packId = params.id;
	const res = await daemonFetch(`/api/detection-packs/${encodeURIComponent(packId)}/install`, {
		method: 'POST',
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
