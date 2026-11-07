import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

// PR 2 (reliability): 11.2 s cold on the G11, so the 10 s default showed an error card
const RISK_SCORES_TIMEOUT_MS = 30_000;

/**
 * GET /api/risk/scores
 * Proxies to the daemon's GET /api/risk/scores endpoint.
 * Returns risk scores for all monitored devices.
 */
export const GET: RequestHandler = async ({ url }) => {
	// OLD CODE START — dropped the query, so from/to/limit never reached the daemon
	// const res = await daemonFetch('/api/risk/scores');
	// OLD CODE END
	const params = new URLSearchParams();
	for (const key of ['from', 'to', 'limit']) {
		const value = url.searchParams.get(key);
		if (value) params.set(key, value);
	}
	const query = params.toString() ? `?${params.toString()}` : '';
	// OLD CODE START — PR 2 (reliability): the 10 s default, below the cold daemon time
	// const res = await daemonFetch(`/api/risk/scores${query}`);
	// OLD CODE END
	const res = await daemonFetch(`/api/risk/scores${query}`, undefined, RISK_SCORES_TIMEOUT_MS);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
