import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/tshark/fields?protocol=X
 * Proxies to the daemon's GET /api/tshark/fields endpoint,
 * forwarding the optional `protocol` query parameter.
 */
export const GET: RequestHandler = async ({ url }) => {
	const protocol = url.searchParams.get('protocol');
	const query = protocol ? `?protocol=${encodeURIComponent(protocol)}` : '';
	const res = await daemonFetch(`/api/tshark/fields${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
