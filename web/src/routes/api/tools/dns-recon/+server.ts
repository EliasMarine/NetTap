import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
// OLD CODE: import { daemonFetch } from '$lib/server/daemon.js'; (NET-203)
import { daemonFetch, TOOL_TIMEOUT_MS } from '$lib/server/daemon.js';

/**
 * POST /api/tools/dns-recon
 * Proxies the request body to the daemon's POST /api/tools/dns-recon endpoint.
 */
export const POST: RequestHandler = async ({ request }) => {
	let body: Record<string, unknown>;
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON request body.' }, { status: 400 });
	}

	// OLD CODE: the same call with daemonFetch's 10 s default (NET-203: below the daemon's own limit)
	const res = await daemonFetch(
		'/api/tools/dns-recon',
		{
			method: 'POST',
			body: JSON.stringify(body),
		},
		TOOL_TIMEOUT_MS['dns-recon']
	);

	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
