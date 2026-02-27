import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { clearAuthCookie } from '$lib/server/middleware.js';

export const POST: RequestHandler = async (event) => {
	clearAuthCookie(event);
	throw redirect(302, '/login');
};
