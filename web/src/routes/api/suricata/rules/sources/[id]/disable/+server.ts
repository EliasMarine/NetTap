import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/suricata/rules/sources/[id]/disable
 * Proxies to the daemon's POST /api/suricata/rules/sources/{id}/disable endpoint.
 */
export const POST: RequestHandler = async ({ params }) => {
	const res = await daemonFetch(`/api/suricata/rules/sources/${params.id}/disable`, {
		method: 'POST',
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
