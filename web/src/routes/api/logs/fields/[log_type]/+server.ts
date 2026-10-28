import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

export const GET: RequestHandler = async ({ params }) => {
	const res = await daemonFetch(`/api/logs/fields/${params.log_type}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse response' }));
	return json(data, { status: res.status });
};
