import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch, RULE_UPDATE_TIMEOUT_MS } from '$lib/server/daemon.js';

/**
 * GET /api/suricata/rules/custom
 * Proxies to the daemon's GET /api/suricata/rules/custom endpoint.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/suricata/rules/custom');
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * POST /api/suricata/rules/custom
 * Proxies to the daemon's POST /api/suricata/rules/custom endpoint.
 */
export const POST: RequestHandler = async ({ request }) => {
	const body = await request.text();
	// OLD CODE START — NET-191 slice 3: the daemon now tests the rules with Suricata and reloads it, past the 10 s default
	// const res = await daemonFetch('/api/suricata/rules/custom', {
	// 	method: 'POST',
	// 	body,
	// });
	// OLD CODE END
	const res = await daemonFetch('/api/suricata/rules/custom', { method: 'POST', body }, RULE_UPDATE_TIMEOUT_MS);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
