import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonJSON } from '$lib/server/daemon.js';

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
		// down an active DHCP gateway first, so wait up to 60 s.
		const { data, error, status } = await daemonJSON(
			'/api/setup/configure',
			{
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body),
			},
			60_000
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
