import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';

export const GET: RequestHandler = async (event) => {
	if (!event.locals.user) {
		return json({ authenticated: false }, { status: 401 });
	}

	return json({
		authenticated: true,
		user: {
			username: event.locals.user.username,
			role: event.locals.user.role,
		},
	});
};
