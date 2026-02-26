import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/reports/schedules/:id
 * Proxies to the daemon's GET /api/reports/schedules/:id endpoint.
 * Returns a single report schedule by ID.
 */
export const GET: RequestHandler = async ({ params }) => {
	const scheduleId = params.id;
	const res = await daemonFetch(`/api/reports/schedules/${encodeURIComponent(scheduleId)}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * PUT /api/reports/schedules/:id
 * Proxies to the daemon's PUT /api/reports/schedules/:id endpoint.
 * Updates an existing report schedule.
 */
export const PUT: RequestHandler = async ({ params, request }) => {
	const scheduleId = params.id;
	let body: Record<string, unknown> = {};
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	const res = await daemonFetch(`/api/reports/schedules/${encodeURIComponent(scheduleId)}`, {
		method: 'PUT',
		body: JSON.stringify(body),
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * DELETE /api/reports/schedules/:id
 * Proxies to the daemon's DELETE /api/reports/schedules/:id endpoint.
 * Deletes a report schedule.
 */
export const DELETE: RequestHandler = async ({ params }) => {
	const scheduleId = params.id;
	const res = await daemonFetch(`/api/reports/schedules/${encodeURIComponent(scheduleId)}`, {
		method: 'DELETE',
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
