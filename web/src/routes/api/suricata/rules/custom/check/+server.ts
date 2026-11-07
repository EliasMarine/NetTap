import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/suricata/rules/custom/check
 * Runs the daemon's owner rules validator only (NET-191 slice 3); passes its status and body through.
 */
export const POST: RequestHandler = async ({ request }) => {
	const body = await request.text();
	const res = await daemonFetch('/api/suricata/rules/custom/check', { method: 'POST', body });
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
