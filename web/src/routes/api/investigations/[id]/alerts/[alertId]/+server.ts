import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * DELETE /api/investigations/:id/alerts/:alertId
 * Proxies to the daemon's DELETE /api/investigations/:id/alerts/:alertId endpoint.
 * Unlinks an alert from an investigation.
 */
export const DELETE: RequestHandler = async ({ params }) => {
	const { id, alertId } = params;
	const res = await daemonFetch(
		`/api/investigations/${encodeURIComponent(id)}/alerts/${encodeURIComponent(alertId)}`,
		{
			method: 'DELETE',
		}
	);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
