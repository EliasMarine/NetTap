// OLD CODE START — original single-step admin creation page.server.ts
// Replaced with multi-step wizard that integrates admin account creation as step 5.
// The admin creation logic is preserved below; it now runs only when step=5 data is submitted.
// OLD CODE END

import type { Actions, PageServerLoad } from './$types.js';
import { fail, redirect } from '@sveltejs/kit';
// OLD CODE START — createUser had no first-admin race protection (2026-10-29)
// import { createUser, hasUsers } from '$lib/server/auth.js';
// OLD CODE END
import {
	clearSetupCode,
	createFirstAdmin,
	ensureSetupCode,
	generateToken,
	hasUsers,
	SetupAlreadyComplete,
	setupToken,
} from '$lib/server/auth.js';
import { checkSetupCode } from '$lib/server/login.js';
import { clearSetupCookie, hasSetupCookie, setAuthCookie, setSetupCookie } from '$lib/server/middleware.js';

// OLD CODE START — NET-229 follow-up: the code is now typed on the Welcome step, before any API call
// /** A13 (NET-229): an open wizard always has a setup code to check against, even if the file was removed. */
// export const load: PageServerLoad = () => {
// 	ensureSetupCode();
// };
// OLD CODE END
/**
 * A13 (NET-229): an open wizard always has a setup code to check against, even if the file was
 * removed. `setupVerified` says whether this browser already typed it. With an admin there is no
 * code (only a signed-in admin reaches /setup then), so existing installs never see the prompt.
 */
export const load: PageServerLoad = (event) => {
	if (!ensureSetupCode()) return { setupVerified: true };
	return { setupVerified: hasSetupCookie(event) };
};

export const actions: Actions = {
	/**
	 * verifyCode — the Welcome step's setup code (NET-229 follow-up). A right code sets the setup
	 * cookie, which the wizard's API calls need while no admin exists.
	 */
	verifyCode: async (event) => {
		const token = setupToken();
		if (!token) {
			throw redirect(302, '/login');
		}
		const data = await event.request.formData();
		// OLD CODE: checkSetupCode(event.getClientAddress(), …) (review L4: its own limit, not per address)
		const code = checkSetupCode(data.get('setupCode')?.toString() ?? '');
		if (!code.ok) {
			return fail(code.status, { error: code.error });
		}
		setSetupCookie(event, token);
		return { verified: true };
	},

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

		// A13 (NET-229): only someone who can read the code on the box may claim it. Checked first,
		// so nothing else about the request is looked at for a caller without it. The wizard proves it
		// with the setup cookie from the Welcome step; scripts and tests post the code itself.
		// OLD CODE START — NET-229 follow-up: the wizard now sends the cookie, not the field
		// const code = checkSetupCode(event.getClientAddress(), data.get('setupCode')?.toString() ?? '');
		// if (!code.ok) {
		// 	return fail(code.status, { error: code.error, username: username ?? '' });
		// }
		// OLD CODE END
		if (!hasSetupCookie(event)) {
			const typed = data.get('setupCode')?.toString() ?? '';
			// The wizard's cookie expired (24 h) or the code was replaced: back to the Welcome step
			if (typed === '') {
				return fail(401, {
					error: 'Enter the setup code again: reload this page and type it on the first step.',
					username: username ?? '',
				});
			}
			// OLD CODE: const code = checkSetupCode(event.getClientAddress(), typed); (review L4)
			const code = checkSetupCode(typed);
			if (!code.ok) {
				return fail(code.status, { error: code.error, username: username ?? '' });
			}
		}

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

		// OLD CODE START — check-then-create raced: two requests could both create an admin (2026-10-29)
		// try {
		// 	await createUser(username, password, 'admin');
		// } catch (err) {
		// 	return fail(500, {
		// 		error: err instanceof Error ? err.message : 'Failed to create user.',
		// 		username,
		// 	});
		// }
		// OLD CODE END
		try {
			await createFirstAdmin(username, password);
		} catch (err) {
			if (err instanceof SetupAlreadyComplete) {
				throw redirect(302, '/login');
			}
			// OLD CODE START — NET-229 (B-p): the reply carried the exception text (file paths, errno)
			// return fail(500, {
			// 	error: err instanceof Error ? err.message : 'Failed to create user.',
			// 	username,
			// });
			// OLD CODE END
			console.error('Setup: creating the first admin failed:', err);
			return fail(500, { error: "Couldn't create the account. The web container's log has the details.", username });
		}
		// Single use: the code is gone once the admin exists. A leftover file matches nothing (an admin
		// exists) and the next start removes it, so a failed removal doesn't fail the setup.
		try {
			clearSetupCode();
		} catch (err) {
			console.error('Setup: removing the used setup code failed:', err);
		}
		clearSetupCookie(event);

		// Sign in only the winner, so the rest of the wizard and Go Live run
		// with a session once the setup and bridge routes stop being public.
		setAuthCookie(event, generateToken({ username, role: 'admin' }));
		return { success: true, username };
	},
};
