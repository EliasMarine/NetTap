import { redirect } from '@sveltejs/kit';
import { setupTokenValid, verifyToken } from './auth.js';
import type { RequestEvent } from '@sveltejs/kit';
import type { TokenPayload } from './auth.js';

/**
 * Extracts and verifies the JWT from the request cookies.
 * Returns the token payload if valid, or null otherwise.
 */
export function getAuthFromCookies(event: RequestEvent): TokenPayload | null {
	const token = event.cookies.get('nettap_token');
	if (!token) return null;
	return verifyToken(token);
}

/**
 * Requires authentication. If the user is not authenticated,
 * throws a redirect to /login.
 * Use in +page.server.ts load functions or form actions.
 */
export function requireAuth(event: RequestEvent): TokenPayload {
	const user = getAuthFromCookies(event);
	if (!user) {
		throw redirect(302, '/login');
	}
	return user;
}

/**
 * Sets the JWT cookie on the response.
 */
export function setAuthCookie(event: RequestEvent, token: string): void {
	event.cookies.set('nettap_token', token, {
		path: '/',
		httpOnly: true,
		secure: process.env.NODE_ENV === 'production',
		sameSite: 'lax',
		maxAge: 60 * 60 * 24, // 24 hours
	});
}

/**
 * Clears the JWT cookie.
 */
export function clearAuthCookie(event: RequestEvent): void {
	event.cookies.delete('nettap_token', { path: '/' });
}

// ----- First-run setup cookie (NET-229 follow-up) -----

const SETUP_COOKIE = 'nettap_setup';

/** Set once the setup code is typed on the Welcome step; the wizard's API calls need it. */
export function setSetupCookie(event: RequestEvent, token: string): void {
	event.cookies.set(SETUP_COOKIE, token, {
		path: '/',
		httpOnly: true,
		secure: process.env.NODE_ENV === 'production',
		sameSite: 'lax',
		maxAge: 60 * 60 * 24, // 24 hours
	});
}

export function clearSetupCookie(event: RequestEvent): void {
	event.cookies.delete(SETUP_COOKIE, { path: '/' });
}

/** This browser typed the current setup code. */
export function hasSetupCookie(event: RequestEvent): boolean {
	return setupTokenValid(event.cookies.get(SETUP_COOKIE));
}
