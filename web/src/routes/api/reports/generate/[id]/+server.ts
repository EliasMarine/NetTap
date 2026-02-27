import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/reports/generate/:id
 * Proxies to the daemon's POST /api/reports/generate/:id endpoint.
 * Generates a report on-demand from a schedule.
 */
export const POST: RequestHandler = async ({ params }) => {
	const scheduleId = params.id;
	const res = await daemonFetch(`/api/reports/generate/${encodeURIComponent(scheduleId)}`, {
		method: 'POST',
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
