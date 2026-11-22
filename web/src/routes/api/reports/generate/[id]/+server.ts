import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

// NET-340: the daemon gives a report up to 45 s and answers 409 at once while another is running,
// so 60 s always gets its answer (nginx: 60 s); the default 10 s read as "Daemon unreachable"
const GENERATE_TIMEOUT_MS = 60_000;

/**
 * POST /api/reports/generate/:id
 * Proxies to the daemon's POST /api/reports/generate/:id endpoint.
 * Generates a report on-demand from a schedule.
 */
export const POST: RequestHandler = async ({ params }) => {
	const scheduleId = params.id;
	// OLD CODE START — NET-340: the 10 s default timeout
	// const res = await daemonFetch(`/api/reports/generate/${encodeURIComponent(scheduleId)}`, {
	// 	method: 'POST',
	// });
	// OLD CODE END
	const res = await daemonFetch(`/api/reports/generate/${encodeURIComponent(scheduleId)}`, { method: 'POST' }, GENERATE_TIMEOUT_MS);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
