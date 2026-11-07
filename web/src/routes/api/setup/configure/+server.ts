import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonJSON, RULE_UPDATE_TIMEOUT_MS } from '$lib/server/daemon.js';

/**
 * POST /api/setup/configure — Proxy to daemon POST /api/setup/configure.
 *
 * Writes the capture mode configuration (mirror/bridge) and related
 * environment variables on the NetTap appliance.
 */
export const POST: RequestHandler = async ({ request }) => {
	try {
		const body = await request.json();

		// OLD CODE START — 2026-10-30: default 10 s timeout; saving now restarts capture containers and can take longer
		// const { data, error, status } = await daemonJSON('/api/setup/configure', {
		// 	method: 'POST',
		// 	headers: { 'Content-Type': 'application/json' },
		// 	body: JSON.stringify(body),
		// });
		// OLD CODE END
		// Saving writes the config, restarts the capture containers and may tear
		// down an active DHCP gateway first. Restarting Suricata waits for a
		// running rule update (NET-191), so wait as long as a rule update.
		const { data, error, status } = await daemonJSON(
			'/api/setup/configure',
			{
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body),
			},
			// OLD CODE START — NET-191 slice 2: a Suricata restart now waits up to 240 s for the rules lock
			// 60_000
			// OLD CODE END
			RULE_UPDATE_TIMEOUT_MS
		);

		if (error) {
			return json({ error }, { status });
		}

		return json(data);
	} catch (err) {
		return json(
			{ error: err instanceof Error ? err.message : 'Failed to save configuration' },
			{ status: 500 }
		);
	}
};
