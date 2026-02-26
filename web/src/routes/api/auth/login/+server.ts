import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { getUser, verifyPassword, generateToken } from '$lib/server/auth.js';
import { setAuthCookie } from '$lib/server/middleware.js';

// ----- Simple in-memory rate limiter -----
const rateLimitMap = new Map<string, { count: number; resetAt: number }>();
const MAX_ATTEMPTS = 5;
const WINDOW_MS = 60_000; // 1 minute

function checkRateLimit(ip: string): boolean {
	const now = Date.now();
	const entry = rateLimitMap.get(ip);

	if (!entry || now > entry.resetAt) {
		rateLimitMap.set(ip, { count: 1, resetAt: now + WINDOW_MS });
		return true;
	}

	if (entry.count >= MAX_ATTEMPTS) {
		return false;
	}

	entry.count++;
	return true;
}

// Periodic cleanup to prevent memory leaks
setInterval(() => {
	const now = Date.now();
	for (const [ip, entry] of rateLimitMap) {
		if (now > entry.resetAt) {
			rateLimitMap.delete(ip);
		}
	}
}, 60_000);

export const POST: RequestHandler = async (event) => {
	const clientIp = event.getClientAddress();

	if (!checkRateLimit(clientIp)) {
		return json(
			{ error: 'Too many login attempts. Please wait a minute and try again.' },
			{ status: 429 }
		);
	}

	let body: { username?: string; password?: string };
	try {
		body = await event.request.json();
	} catch {
		return json({ error: 'Invalid request body.' }, { status: 400 });
	}

	const { username, password } = body;
	if (!username || !password) {
		return json({ error: 'Username and password are required.' }, { status: 400 });
	}

	const user = getUser(username.trim());
	if (!user) {
		return json({ error: 'Invalid username or password.' }, { status: 401 });
	}

	const valid = await verifyPassword(password, user.passwordHash);
	if (!valid) {
		return json({ error: 'Invalid username or password.' }, { status: 401 });
	}

	const token = generateToken({ username: user.username, role: user.role });
	setAuthCookie(event, token);

	return json({
		success: true,
		user: { username: user.username, role: user.role },
	});
};
