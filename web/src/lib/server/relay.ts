import { json } from '@sveltejs/kit';

/**
 * A daemon answer passed on with its status. A body that isn't JSON is a 502, even on a 2xx: the
 * page would otherwise take `{ error }` for the settings it asked for (NET-224 review L1).
 */
export async function relayJSON(res: Response): Promise<Response> {
	const data = await res.json().catch(() => undefined);
	if (data === undefined) {
		return json({ error: "NetTap's answer couldn't be read." }, { status: res.ok ? 502 : res.status });
	}
	return json(data, { status: res.status });
}
