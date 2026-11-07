import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch, RULE_UPDATE_TIMEOUT_MS } from '$lib/server/daemon.js';

/**
 * POST /api/capture/dhcp/enable — proxy to the daemon's endpoint of the same name.
 *
 * Enabling runs a fresh preflight (~3 s DHCP probe), applies routing, firewall
 * and boot config, then restarts the capture containers. That outlasts the
 * catch-all proxy's 10 s default. Restarting Suricata waits for a running rule
 * update to finish (NET-191), so this route waits as long as a rule update.
 * Auth is the same as the catch-all: hooks.server.ts gates by path.
 */
export const POST: RequestHandler = async ({ request }) => {
	const body = await request.text();
	const res = await daemonFetch(
		'/api/capture/dhcp/enable',
		{ method: 'POST', ...(body ? { body } : {}) },
		// OLD CODE START — NET-191 slice 2: a Suricata restart now waits up to 240 s for the rules lock
		// 60_000
		// OLD CODE END
		RULE_UPDATE_TIMEOUT_MS
	);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
