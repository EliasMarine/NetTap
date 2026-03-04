import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

export const POST: RequestHandler = async () => {
	const res = await daemonFetch('/api/bridge/teardown', { method: 'POST' });
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
