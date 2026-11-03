import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/capture/dhcp/disable — proxy to the daemon's endpoint of the same name.
 *
 * Stopping the DHCP server waits on the capture lock, which an enable or a
 * setup save may hold for longer than the catch-all's 10 s default, so this
 * route waits up to 60 s. Auth is the same as the catch-all: hooks.server.ts
 * gates by path.
 */
export const POST: RequestHandler = async () => {
	const res = await daemonFetch('/api/capture/dhcp/disable', { method: 'POST' }, 60_000);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
