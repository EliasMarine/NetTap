import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
// OLD CODE START — CR-034: lookup + verify moved into attemptLogin, which throttles them
// import { getUser, verifyPassword, generateToken } from '$lib/server/auth.js';
// OLD CODE END
import { generateToken } from '$lib/server/auth.js';
import { attemptLogin } from '$lib/server/login.js';
import { setAuthCookie } from '$lib/server/middleware.js';

// OLD CODE START — CR-034: this limiter guarded only this endpoint (the login
// form never calls it) and, with no ADDRESS_HEADER, keyed every client on
// nginx's IP. Replaced by $lib/server/login.ts, shared with the form action.
// // ----- Simple in-memory rate limiter -----
// const rateLimitMap = new Map<string, { count: number; resetAt: number }>();
// const MAX_ATTEMPTS = 5;
// const WINDOW_MS = 60_000; // 1 minute
//
// function checkRateLimit(ip: string): boolean {
// 	const now = Date.now();
// 	const entry = rateLimitMap.get(ip);
//
// 	if (!entry || now > entry.resetAt) {
// 		rateLimitMap.set(ip, { count: 1, resetAt: now + WINDOW_MS });
// 		return true;
// 	}
//
// 	if (entry.count >= MAX_ATTEMPTS) {
// 		return false;
// 	}
//
// 	entry.count++;
// 	return true;
// }
//
// // Periodic cleanup to prevent memory leaks
// setInterval(() => {
// 	const now = Date.now();
// 	for (const [ip, entry] of rateLimitMap) {
// 		if (now > entry.resetAt) {
// 			rateLimitMap.delete(ip);
// 		}
// 	}
// }, 60_000);
// OLD CODE END

export const POST: RequestHandler = async (event) => {
	// OLD CODE START — CR-034: limiter moved into attemptLogin
	// const clientIp = event.getClientAddress();
	//
	// if (!checkRateLimit(clientIp)) {
	// 	return json(
	// 		{ error: 'Too many login attempts. Please wait a minute and try again.' },
	// 		{ status: 429 }
	// 	);
	// }
	// OLD CODE END

	let body: { username?: unknown; password?: unknown };
	try {
		body = await event.request.json();
	} catch {
		return json({ error: 'Invalid request body.' }, { status: 400 });
	}

	// OLD CODE START — CR-034: a non-string username threw on trim() (500)
	// const { username, password } = body;
	// if (!username || !password) {
	// OLD CODE END
	const username = typeof body?.username === 'string' ? body.username.trim() : '';
	const password = typeof body?.password === 'string' ? body.password : '';
	if (!username || !password) {
		return json({ error: 'Username and password are required.' }, { status: 400 });
	}

	// OLD CODE START — CR-034: unthrottled, and unknown usernames skipped the hash (timing leak)
	// const user = getUser(username.trim());
	// if (!user) {
	// 	return json({ error: 'Invalid username or password.' }, { status: 401 });
	// }
	//
	// const valid = await verifyPassword(password, user.passwordHash);
	// if (!valid) {
	// 	return json({ error: 'Invalid username or password.' }, { status: 401 });
	// }
	// OLD CODE END
	const result = await attemptLogin(event.getClientAddress(), username, password);
	if (!result.ok) {
		const headers = result.retryAfter ? { 'Retry-After': String(result.retryAfter) } : undefined;
		return json({ error: result.error }, { status: result.status, headers });
	}
	const { user } = result;

	const token = generateToken({ username: user.username, role: user.role });
	setAuthCookie(event, token);

	return json({
		success: true,
		user: { username: user.username, role: user.role },
	});
};
