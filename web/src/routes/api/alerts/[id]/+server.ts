import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/alerts/:id
 * Proxies to the daemon's GET /api/alerts/:id endpoint.
 * Returns a single alert detail by OpenSearch _id.
 */
export const GET: RequestHandler = async ({ params }) => {
	const alertId = params.id;
	const res = await daemonFetch(`/api/alerts/${encodeURIComponent(alertId)}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * POST /api/alerts/:id/acknowledge
 * Proxies to the daemon's POST /api/alerts/:id/acknowledge endpoint.
 * Marks an alert as acknowledged.
 */
export const POST: RequestHandler = async ({ params, request }) => {
	const alertId = params.id;
	let body: Record<string, unknown> = {};
	try {
		body = await request.json();
	} catch {
		// No body is acceptable — daemon will use defaults
	}

	const res = await daemonFetch(`/api/alerts/${encodeURIComponent(alertId)}/acknowledge`, {
		method: 'POST',
		body: JSON.stringify(body),
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
