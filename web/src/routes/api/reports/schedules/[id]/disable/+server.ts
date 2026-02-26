import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/reports/schedules/:id/disable
 * Proxies to the daemon's POST /api/reports/schedules/:id/disable endpoint.
 * Disables a report schedule.
 */
export const POST: RequestHandler = async ({ params }) => {
	const scheduleId = params.id;
	const res = await daemonFetch(
		`/api/reports/schedules/${encodeURIComponent(scheduleId)}/disable`,
		{ method: 'POST' },
	);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
