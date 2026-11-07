import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/alerts?from=&to=&severity=&page=1&size=50&sort=&order=
 * Proxies to the daemon's GET /api/alerts endpoint,
 * forwarding all query parameters for paginated alert listing.
 */
export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	const severity = url.searchParams.get('severity');
	const page = url.searchParams.get('page');
	const size = url.searchParams.get('size');
	if (from) params.set('from', from);
	if (to) params.set('to', to);
	if (severity) params.set('severity', severity);
	if (page) params.set('page', page);
	if (size) params.set('size', size);
	const ip = url.searchParams.get('ip');
	if (ip) params.set('ip', ip);
	// NET-160 slice 2b-1: a smart alert's source → destination pair; the daemon validates both
	for (const key of ['src', 'dst']) {
		const value = url.searchParams.get(key);
		if (value) params.set(key, value);
	}
	const signature = url.searchParams.get('signature');
	if (signature) params.set('signature', signature);
	const category = url.searchParams.get('category');
	if (category) params.set('category', category);
	// NET-160 slice 2b-2: one raw Suricata category (rule.category); the daemon validates it
	const suricataCategory = url.searchParams.get('suricata_category');
	if (suricataCategory) params.set('suricata_category', suricataCategory);
	// #146: the alert tables' sort; #147: a category's sub-category. The daemon validates them
	for (const key of ['sort', 'order', 'sub']) {
		const value = url.searchParams.get(key);
		if (value) params.set(key, value);
	}

	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/alerts${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
