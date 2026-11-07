import { json } from '@sveltejs/kit';
import type { RequestEvent } from '@sveltejs/kit';
import { daemonFetch } from '$lib/server/daemon.js';

/**
 * POST /api/packets/download (NET-188): a search's packets as one pcap.
 *
 * Takes `{manifest}` as JSON (the page's fetch) or a form post with a `manifest`
 * field holding the JSON text (a plain form submit, so the browser shows its own
 * download progress). The daemon's stream is passed straight through: when the daemon
 * aborts part-way, this response errors too, so the browser never keeps a
 * complete-looking but short file.
 */

export const DOWNLOAD_HEADERS_TIMEOUT_MS = 60_000;

/** The manifest object from either body shape, or null when it is missing or not an object. */
async function readManifest(request: Request): Promise<Record<string, unknown> | null> {
	const type = request.headers.get('content-type') ?? '';
	let manifest: unknown;
	try {
		if (type.includes('application/json')) {
			manifest = ((await request.json()) as { manifest?: unknown } | null)?.manifest;
		} else if (type.includes('application/x-www-form-urlencoded') || type.includes('multipart/form-data')) {
			const field = (await request.formData()).get('manifest');
			manifest = typeof field === 'string' ? JSON.parse(field) : null;
		}
	} catch {
		return null;
	}
	return manifest && typeof manifest === 'object' && !Array.isArray(manifest)
		? (manifest as Record<string, unknown>)
		: null;
}

export const POST = async ({ request }: RequestEvent): Promise<Response> => {
	const manifest = await readManifest(request);
	if (!manifest) {
		return json({ error: 'Send the search’s manifest to download its packets.' }, { status: 400 });
	}

	// OLD CODE START — NET-188 review: request.signal never fires once the body has been read,
	// and passing a signal turned off daemonFetch's own timeout, so a daemon that never answered
	// left this request waiting forever
	// const res = await daemonFetch('/api/packets/download', {
	// 	method: 'POST',
	// 	body: JSON.stringify({ manifest }),
	// 	signal: request.signal,
	// });
	// OLD CODE END
	// The daemon answers once the first packet is verified (its job stops itself by ~45 s).
	// Only that wait is timed: after the headers, the download lasts as long as the browser
	// reads, and a browser that leaves cancels the body, which closes the daemon's stream.
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), DOWNLOAD_HEADERS_TIMEOUT_MS);
	let res: Response;
	try {
		res = await daemonFetch('/api/packets/download', {
			method: 'POST',
			body: JSON.stringify({ manifest }),
			signal: controller.signal,
		});
	} finally {
		clearTimeout(timer);
	}

	if (!res.ok) {
		const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
		return json(data, { status: res.status });
	}

	const headers = new Headers();
	for (const name of ['content-type', 'content-disposition']) {
		const value = res.headers.get(name);
		if (value) headers.set(name, value);
	}
	return new Response(res.body, { status: res.status, headers });
};
