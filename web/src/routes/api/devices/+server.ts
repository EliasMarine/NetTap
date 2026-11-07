import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

// NET-160 slice 2b-3: a 30-day list pages every device's buckets. scripts/remote/deploy-drill-down.sh
// declares the same value and gates the device's 30-day list at 80% of it; the vitest checks they match.
const DEVICE_LIST_TIMEOUT_MS = 10_000;

/**
 * GET /api/devices?from=&to=&sort=bytes&order=desc&limit=100
 * Proxies to the daemon's GET /api/devices endpoint,
 * forwarding all query parameters for the device inventory listing.
 */
export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	const sort = url.searchParams.get('sort');
	const order = url.searchParams.get('order');
	const limit = url.searchParams.get('limit');
	if (from) params.set('from', from);
	if (to) params.set('to', to);
	if (sort) params.set('sort', sort);
	if (order) params.set('order', order);
	if (limit) params.set('limit', limit);

	const query = params.toString() ? `?${params.toString()}` : '';
	// OLD CODE START — NET-160 slice 2b-3: the default timeout, which nothing tied to the device check
	// const res = await daemonFetch(`/api/devices${query}`);
	// OLD CODE END
	const res = await daemonFetch(`/api/devices${query}`, undefined, DEVICE_LIST_TIMEOUT_MS);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
