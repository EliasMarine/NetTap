import { redirect } from '@sveltejs/kit';
import { verifyToken } from './auth.js';
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
