import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch, TOOL_TIMEOUT_MS } from '$lib/server/daemon.js';

/**
 * POST /api/tools/throughput (NET-266)
 * Proxies one iperf3 run (one direction) to the daemon's POST /api/tools/throughput.
 */
export const POST: RequestHandler = async ({ request }) => {
	let body: Record<string, unknown>;
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON request body.' }, { status: 400 });
	}

	const res = await daemonFetch(
		'/api/tools/throughput',
		{
			method: 'POST',
			body: JSON.stringify(body),
		},
		TOOL_TIMEOUT_MS.throughput
	);

	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
