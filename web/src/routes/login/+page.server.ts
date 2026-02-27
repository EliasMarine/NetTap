import type { Actions } from './$types.js';
import { fail, redirect } from '@sveltejs/kit';
import { getUser, verifyPassword, generateToken } from '$lib/server/auth.js';
import { setAuthCookie } from '$lib/server/middleware.js';

export const actions: Actions = {
	default: async (event) => {
		const data = await event.request.formData();
		const username = data.get('username')?.toString().trim();
		const password = data.get('password')?.toString();

		if (!username || !password) {
			return fail(400, {
				error: 'Username and password are required.',
				username: username ?? '',
			});
		}

		const user = getUser(username);
		if (!user) {
			return fail(401, {
				error: 'Invalid username or password.',
				username,
			});
		}

		const valid = await verifyPassword(password, user.passwordHash);
		if (!valid) {
			return fail(401, {
				error: 'Invalid username or password.',
				username,
			});
		}

		const token = generateToken({ username: user.username, role: user.role });
		setAuthCookie(event, token);

		throw redirect(302, '/');
	},
};
