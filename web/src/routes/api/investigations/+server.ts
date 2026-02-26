import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/investigations?status=&severity=
 * Proxies to the daemon's GET /api/investigations endpoint.
 * Returns filtered list of investigations.
 */
export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	const status = url.searchParams.get('status');
	const severity = url.searchParams.get('severity');
	if (status) params.set('status', status);
	if (severity) params.set('severity', severity);

	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/investigations${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * POST /api/investigations
 * Proxies to the daemon's POST /api/investigations endpoint.
 * Creates a new investigation.
 */
export const POST: RequestHandler = async ({ request }) => {
	let body: Record<string, unknown> = {};
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	const res = await daemonFetch('/api/investigations', {
		method: 'POST',
		body: JSON.stringify(body),
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
