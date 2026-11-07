import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch, RULE_UPDATE_TIMEOUT_MS } from '$lib/server/daemon.js';

/**
 * POST /api/capture/dhcp/disable — proxy to the daemon's endpoint of the same name.
 *
 * Stopping the DHCP server waits on the capture lock, which an enable or a
 * setup save may hold for longer than the catch-all's 10 s default, and
 * restarting Suricata waits for a running rule update (NET-191), so this route
 * waits as long as a rule update. Auth is the same as the catch-all:
 * hooks.server.ts gates by path.
 */
export const POST: RequestHandler = async () => {
	// OLD CODE START — NET-191 slice 2: a Suricata restart now waits up to 240 s for the rules lock
	// const res = await daemonFetch('/api/capture/dhcp/disable', { method: 'POST' }, 60_000);
	// OLD CODE END
	const res = await daemonFetch('/api/capture/dhcp/disable', { method: 'POST' }, RULE_UPDATE_TIMEOUT_MS);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
