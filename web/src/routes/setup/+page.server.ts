// OLD CODE START — original single-step admin creation page.server.ts
// Replaced with multi-step wizard that integrates admin account creation as step 5.
// The admin creation logic is preserved below; it now runs only when step=5 data is submitted.
// OLD CODE END

import type { Actions } from './$types.js';
import { fail, redirect } from '@sveltejs/kit';
import { createUser, hasUsers } from '$lib/server/auth.js';

export const actions: Actions = {
	/**
	 * createAdmin — Handles admin account creation (wizard step 5).
	 * Validates inputs, creates the user via the auth module, and returns
	 * success so the client can redirect to the dashboard.
	 */
	createAdmin: async (event) => {
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

		if (!/^[a-zA-Z0-9_-]+$/.test(username)) {
			return fail(400, {
				error: 'Username can only contain letters, numbers, hyphens, and underscores.',
				username,
			});
		}

		if (password.length < 8) {
			return fail(400, {
				error: 'Password must be at least 8 characters.',
				username,
			});
		}

		if (!/[A-Z]/.test(password)) {
			return fail(400, {
				error: 'Password must contain at least one uppercase letter.',
				username,
			});
		}

		if (!/[a-z]/.test(password)) {
			return fail(400, {
				error: 'Password must contain at least one lowercase letter.',
				username,
			});
		}

		if (!/[0-9]/.test(password)) {
			return fail(400, {
				error: 'Password must contain at least one number.',
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
