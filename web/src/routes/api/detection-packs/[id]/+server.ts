import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/detection-packs/:id
 * Proxies to the daemon's GET /api/detection-packs/:id endpoint.
 * Returns a single detection pack by ID.
 */
export const GET: RequestHandler = async ({ params }) => {
	const packId = params.id;
	const res = await daemonFetch(`/api/detection-packs/${encodeURIComponent(packId)}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * DELETE /api/detection-packs/:id
 * Proxies to the daemon's DELETE /api/detection-packs/:id endpoint.
 * Uninstalls (removes) a detection pack.
 */
export const DELETE: RequestHandler = async ({ params }) => {
	const packId = params.id;
	const res = await daemonFetch(`/api/detection-packs/${encodeURIComponent(packId)}`, {
		method: 'DELETE',
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
