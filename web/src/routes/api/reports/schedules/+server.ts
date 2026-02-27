import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/reports/schedules
 * Proxies to the daemon's GET /api/reports/schedules endpoint.
 * Returns all report schedules.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/reports/schedules');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * POST /api/reports/schedules
 * Proxies to the daemon's POST /api/reports/schedules endpoint.
 * Creates a new report schedule.
 */
export const POST: RequestHandler = async ({ request }) => {
	let body: Record<string, unknown> = {};
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	const res = await daemonFetch('/api/reports/schedules', {
		method: 'POST',
		body: JSON.stringify(body),
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
