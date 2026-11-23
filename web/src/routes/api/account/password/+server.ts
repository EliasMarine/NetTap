import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types.js';
import { SIGN_IN_FIRST } from '$lib/auth-errors.js';
import { generateToken, PASSWORD_MAX_LENGTH, passwordProblem, PasswordChangedElsewhere, updatePassword } from '$lib/server/auth.js';
import { attemptLogin } from '$lib/server/login.js';
import { setAuthCookie } from '$lib/server/middleware.js';
import { legacySecretInEnv } from '$lib/server/session-keys.js';

/**
 * POST /api/account/password, JSON { current, password } (NET-358): the signed-in user changes their
 * password. The current one is checked through the login's own throttle; the new hash is saved by
 * compare-and-swap, so every other session ends and this browser gets a new cookie.
 * CSRF: the hook's Sec-Fetch-Site gate, the sameSite=lax cookie and a JSON body.
 */

const NOT_DURABLE_WARNING =
	"Your new password is active. NetTap couldn't confirm it reached the disk: if the box loses power soon, the old password may work again.";

function refuse(status: number, error: string, headers?: Record<string, string>): Response {
	return json({ error }, { status, headers });
}

/** Both fields as non-empty strings, or null for anything else (bad JSON, or a current password too long to be one). */
async function readFields(request: Request): Promise<{ current: string; password: string } | null> {
	let body: unknown;
	try {
		body = await request.json();
	} catch {
		return null;
	}
	const { current, password } = (body ?? {}) as Record<string, unknown>;
	if (typeof current !== 'string' || typeof password !== 'string' || !current || !password) return null;
	// No password can be longer, so it never reaches argon2 or spends a login attempt (NET-358 review)
	if (current.length > PASSWORD_MAX_LENGTH) return null;
	return { current, password };
}

export const POST: RequestHandler = async (event) => {
	const account = event.locals.user;
	if (!account) return refuse(401, SIGN_IN_FIRST);
	// An older NetTap would still trust sessions signed with JWT_SECRET, so a downgrade could undo the change
	if (legacySecretInEnv()) {
		return refuse(
			409,
			"Remove JWT_SECRET from the web container's settings first: an older NetTap would still trust sessions signed with it."
		);
	}

	const fields = await readFields(event.request);
	if (!fields) return refuse(400, 'Enter your current password and a new one.');
	const { current, password } = fields;
	const problem = passwordProblem(password);
	if (problem) return refuse(400, problem);
	if (password === current) return refuse(400, "Choose a new password that's different from the current one.");

	const login = await attemptLogin(event.getClientAddress(), account.username, current);
	if (!login.ok) {
		// OLD CODE: if (login.status === 429) return refuse(429, login.error, { 'Retry-After': String(login.retryAfter) }); (NET-358 review: "undefined" when no wait was given)
		if (login.status === 429) return refuse(429, login.error, login.retryAfter ? { 'Retry-After': String(login.retryAfter) } : undefined);
		return refuse(401, "Your current password isn't right.");
	}

	let saved: Awaited<ReturnType<typeof updatePassword>>;
	try {
		saved = await updatePassword(account.username, login.user.passwordHash, password);
	} catch (err) {
		if (err instanceof PasswordChangedElsewhere) {
			return refuse(409, 'Your password was just changed in another window. Sign in again with the new password.');
		}
		console.error(`Changing the password for ${account.username} failed:`, err);
		return refuse(500, "Couldn't save the new password. The web container's log has the details.");
	}

	setAuthCookie(event, generateToken(saved.user));
	console.info(`Password changed for ${account.username}.`);
	return json(saved.durable ? { success: true } : { success: true, warning: NOT_DURABLE_WARNING });
};
