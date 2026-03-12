import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

export const GET: RequestHandler = async ({ url }) => {
	const params = new URLSearchParams();
	for (const [key, value] of url.searchParams) {
		params.set(key, value);
	}
	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await daemonFetch(`/api/logs/search${query}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse response' }));
	return json(data, { status: res.status });
};
