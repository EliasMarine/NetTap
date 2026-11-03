import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/capture/dhcp/enable — proxy to the daemon's endpoint of the same name.
 *
 * Enabling runs a fresh preflight (~3 s DHCP probe), applies routing, firewall
 * and boot config, then restarts the capture containers. That outlasts the
 * catch-all proxy's 10 s default, so this route waits up to 60 s.
 * Auth is the same as the catch-all: hooks.server.ts gates by path.
 */
export const POST: RequestHandler = async ({ request }) => {
	const body = await request.text();
	const res = await daemonFetch(
		'/api/capture/dhcp/enable',
		{ method: 'POST', ...(body ? { body } : {}) },
		60_000
	);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
