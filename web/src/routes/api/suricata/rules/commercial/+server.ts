import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch, RULE_UPDATE_TIMEOUT_MS } from '$lib/server/daemon.js';

/**
 * GET /api/suricata/rules/commercial
 * Proxies to the daemon's GET /api/suricata/rules/commercial endpoint.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/suricata/rules/commercial');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * POST /api/suricata/rules/commercial
 * Proxies to the daemon's POST /api/suricata/rules/commercial endpoint.
 * The body holds the ET Pro code: it is forwarded unchanged and never logged.
 */
export const POST: RequestHandler = async ({ request }) => {
	const body = await request.text();
	// OLD CODE START — NET-191 slice 2: the daemon checks the code with Proofpoint and restarts Suricata, past the 10 s default
	// const res = await daemonFetch('/api/suricata/rules/commercial', {
	// 	method: 'POST',
	// 	body,
	// });
	// OLD CODE END
	const res = await daemonFetch('/api/suricata/rules/commercial', { method: 'POST', body }, RULE_UPDATE_TIMEOUT_MS);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * DELETE /api/suricata/rules/commercial
 * Removes the ET Pro code; the daemon restarts Suricata on ET Open.
 */
export const DELETE: RequestHandler = async () => {
	const res = await daemonFetch('/api/suricata/rules/commercial', { method: 'DELETE' }, RULE_UPDATE_TIMEOUT_MS);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
