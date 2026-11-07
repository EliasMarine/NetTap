import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { daemonFetch, RULE_UPDATE_TIMEOUT_MS } from '$lib/server/daemon.js';

/** The daemon's JSON with its status; a reply that isn't JSON is a 502, never passed on as the daemon's 2xx (NET-191 slice 3). */
async function relay(res: Response): Promise<Response> {
	const data = await res.json().catch(() => undefined);
	return data === undefined
		? json({ error: "NetTap's daemon sent a reply that couldn't be read." }, { status: 502 })
		: json(data, { status: res.status });
}

/**
 * GET /api/suricata/rules/custom
 * Proxies to the daemon's GET /api/suricata/rules/custom endpoint.
 */
export const GET: RequestHandler = async () => {
	const res = await daemonFetch('/api/suricata/rules/custom');
	// OLD CODE START — NET-191 slice 3: a non-JSON reply kept the daemon's status, so a 200 read as an empty rules file
	// const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	// return json(data, { status: res.status });
	// OLD CODE END
	return relay(res);
};

/**
 * POST /api/suricata/rules/custom
 * Proxies to the daemon's POST /api/suricata/rules/custom endpoint.
 */
export const POST: RequestHandler = async ({ request }) => {
	const body = await request.text();
	// OLD CODE START — NET-191 slice 3: the daemon now tests the rules with Suricata and reloads it, past the 10 s default
	// const res = await daemonFetch('/api/suricata/rules/custom', {
	// 	method: 'POST',
	// 	body,
	// });
	// OLD CODE END
	const res = await daemonFetch('/api/suricata/rules/custom', { method: 'POST', body }, RULE_UPDATE_TIMEOUT_MS);
	// OLD CODE START — NET-191 slice 3: a non-JSON 200 passed through as a save
	// const data = await res.json().catch(() => ({ error: 'Failed to parse daemon response' }));
	// return json(data, { status: res.status });
	// OLD CODE END
	return relay(res);
};
