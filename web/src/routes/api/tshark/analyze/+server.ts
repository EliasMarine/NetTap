import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/tshark/analyze
 * Proxies the request body to the daemon's POST /api/tshark/analyze endpoint.
 */
export const POST: RequestHandler = async ({ request }) => {
	let body: Record<string, unknown>;
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON request body.' }, { status: 400 });
	}

	// TShark analysis can take 30+ seconds for large PCAPs — use 60s timeout
	// instead of the default 10s to prevent premature proxy timeouts.
	const res = await daemonFetch('/api/tshark/analyze', {
		method: 'POST',
		body: JSON.stringify(body),
	}, 60_000);

	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
