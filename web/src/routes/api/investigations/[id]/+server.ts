import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * GET /api/investigations/:id
 * Proxies to the daemon's GET /api/investigations/:id endpoint.
 * Returns a single investigation by ID.
 */
export const GET: RequestHandler = async ({ params }) => {
	const id = params.id;
	const res = await daemonFetch(`/api/investigations/${encodeURIComponent(id)}`);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * PUT /api/investigations/:id
 * Proxies to the daemon's PUT /api/investigations/:id endpoint.
 * Updates an existing investigation.
 */
export const PUT: RequestHandler = async ({ params, request }) => {
	const id = params.id;
	let body: Record<string, unknown> = {};
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	const res = await daemonFetch(`/api/investigations/${encodeURIComponent(id)}`, {
		method: 'PUT',
		body: JSON.stringify(body),
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * DELETE /api/investigations/:id
 * Proxies to the daemon's DELETE /api/investigations/:id endpoint.
 * Deletes an investigation.
 */
export const DELETE: RequestHandler = async ({ params }) => {
	const id = params.id;
	const res = await daemonFetch(`/api/investigations/${encodeURIComponent(id)}`, {
		method: 'DELETE',
	});
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
