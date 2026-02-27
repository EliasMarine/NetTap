import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/search/suggest?q=partial
 * Proxies to the daemon's GET /api/search/suggest endpoint.
 * Returns typeahead suggestions for partial query strings.
 */
export const GET: RequestHandler = async ({ url }) => {
	const q = url.searchParams.get('q') || '';
	const params = new URLSearchParams();
	if (q) params.set('q', q);

	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/search/suggest${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
