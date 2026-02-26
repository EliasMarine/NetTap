import type { Actions } from './$types.js';
import { fail, redirect } from '@sveltejs/kit';
import { createUser, hasUsers } from '$lib/server/auth.js';

export const actions: Actions = {
	default: async (event) => {
		// If users already exist, don't allow setup
		if (hasUsers()) {
			throw redirect(302, '/login');
		}

		const data = await event.request.formData();
		const username = data.get('username')?.toString().trim();
		const password = data.get('password')?.toString();
		const confirmPassword = data.get('confirmPassword')?.toString();

		if (!username || !password || !confirmPassword) {
			return fail(400, {
				error: 'All fields are required.',
				username: username ?? '',
			});
		}

		if (username.length < 3) {
			return fail(400, {
				error: 'Username must be at least 3 characters.',
				username,
			});
		}

		if (password.length < 8) {
			return fail(400, {
				error: 'Password must be at least 8 characters.',
				username,
			});
		}

		if (password !== confirmPassword) {
			return fail(400, {
				error: 'Passwords do not match.',
				username,
			});
		}

		try {
			await createUser(username, password, 'admin');
		} catch (err) {
			return fail(500, {
				error: err instanceof Error ? err.message : 'Failed to create user.',
				username,
			});
		}

		return { success: true, username };
	},
};
