import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';

export const GET: RequestHandler = async (event) => {
	if (!event.locals.user) {
		return json({ authenticated: false }, { status: 401 });
	}

	const { username, role } = event.locals.user;
	// nginx's auth_request reads these to log the user into Dashboards (CR-003)
	return json(
		{ authenticated: true, user: { username, role } },
		{ headers: { 'X-NetTap-User': username, 'X-NetTap-Role': role } }
	);
};
