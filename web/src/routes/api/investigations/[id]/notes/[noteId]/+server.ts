import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * PUT /api/investigations/:id/notes/:noteId
 * Proxies to the daemon's PUT /api/investigations/:id/notes/:noteId endpoint.
 * Updates a note on an investigation.
 */
export const PUT: RequestHandler = async ({ params, request }) => {
	const { id, noteId } = params;
	let body: Record<string, unknown> = {};
	try {
		body = await request.json();
	} catch {
		return json({ error: 'Invalid JSON body' }, { status: 400 });
	}

	const res = await daemonFetch(
		`/api/investigations/${encodeURIComponent(id)}/notes/${encodeURIComponent(noteId)}`,
		{
			method: 'PUT',
			body: JSON.stringify(body),
		}
	);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};

/**
 * DELETE /api/investigations/:id/notes/:noteId
 * Proxies to the daemon's DELETE /api/investigations/:id/notes/:noteId endpoint.
 * Deletes a note from an investigation.
 */
export const DELETE: RequestHandler = async ({ params }) => {
	const { id, noteId } = params;
	const res = await daemonFetch(
		`/api/investigations/${encodeURIComponent(id)}/notes/${encodeURIComponent(noteId)}`,
		{
			method: 'DELETE',
		}
	);
	const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	return json(data, { status: res.status });
};
