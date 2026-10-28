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

		const { data, error, status } = await daemonJSON('/api/setup/configure', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body),
		});

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
