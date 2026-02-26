import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/cyberchef/recipes
 * Proxies to the daemon's GET /api/cyberchef/recipes endpoint.
 * Supports optional ?category= query parameter.
 */
export const GET: RequestHandler = async ({ url }) => {
	const category = url.searchParams.get('category');
	const params = category ? `?category=${encodeURIComponent(category)}` : '';
	const res = await daemonFetch(`/api/cyberchef/recipes${params}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
