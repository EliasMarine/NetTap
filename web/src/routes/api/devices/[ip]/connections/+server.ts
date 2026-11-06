import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/devices/{ip}/connections?from=&to=&page=1&size=50&sort=time&order=desc
 * Proxies to the daemon's GET /api/devices/{ip}/connections endpoint,
 * forwarding the paging, time range and sort parameters (the daemon validates them).
 */
export const GET: RequestHandler = async ({ url, params }) => {
	const queryParams = new URLSearchParams();
	const from = url.searchParams.get('from');
	const to = url.searchParams.get('to');
	const page = url.searchParams.get('page');
	const size = url.searchParams.get('size');
	if (from) queryParams.set('from', from);
	if (to) queryParams.set('to', to);
	if (page) queryParams.set('page', page);
	if (size) queryParams.set('size', size);
	// #143: sort and order were dropped here, so the device page's column sort (#140) never
	// reached the daemon: the arrow changed and the rows stayed newest first
	const sort = url.searchParams.get('sort');
	const order = url.searchParams.get('order');
	if (sort) queryParams.set('sort', sort);
	if (order) queryParams.set('order', order);
	// NET-158: the protocol filter runs on the daemon now, over every page
	const proto = url.searchParams.get('proto');
	if (proto) queryParams.set('proto', proto);

	const query = queryParams.toString() ? `?${queryParams.toString()}` : '';
	const res = await daemonFetch(`/api/devices/${encodeURIComponent(params.ip)}/connections${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
