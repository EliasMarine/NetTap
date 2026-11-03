import type { Actions } from './$types.js';
import { fail, redirect } from '@sveltejs/kit';
// OLD CODE START — CR-034: lookup + verify moved into attemptLogin, which throttles them
// import { getUser, verifyPassword, generateToken } from '$lib/server/auth.js';
// OLD CODE END
import { generateToken } from '$lib/server/auth.js';
import { attemptLogin } from '$lib/server/login.js';
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

		// OLD CODE START — CR-034: no throttling, and unknown usernames returned
		// before any hash ran, so timing revealed which usernames exist
		// const user = getUser(username);
		// if (!user) {
		// 	return fail(401, {
		// 		error: 'Invalid username or password.',
		// 		username,
		// 	});
		// }
		//
		// const valid = await verifyPassword(password, user.passwordHash);
		// if (!valid) {
		// 	return fail(401, {
		// 		error: 'Invalid username or password.',
		// 		username,
		// 	});
		// }
		// OLD CODE END
		const result = await attemptLogin(event.getClientAddress(), username, password);
		if (!result.ok) {
			return fail(result.status, { error: result.error, username });
		}
		const { user } = result;

		const token = generateToken({ username: user.username, role: user.role });
		setAuthCookie(event, token);

		throw redirect(302, '/');
	},
};
