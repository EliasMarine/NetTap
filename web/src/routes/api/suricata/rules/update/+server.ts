import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch, RULE_UPDATE_TIMEOUT_MS } from '$lib/server/daemon.js';

/**
 * POST /api/suricata/rules/update
 * Proxies to the daemon's POST /api/suricata/rules/update endpoint.
 */
export const POST: RequestHandler = async () => {
	// OLD CODE START — NET-191 slice 2: the 10 s default cut off an update that takes minutes
	// const res = await daemonFetch('/api/suricata/rules/update', { method: 'POST' });
	// OLD CODE END
	const res = await daemonFetch('/api/suricata/rules/update', { method: 'POST' }, RULE_UPDATE_TIMEOUT_MS);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
