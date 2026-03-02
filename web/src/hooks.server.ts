import type { Handle } from '@sveltejs/kit';
import { redirect } from '@sveltejs/kit';
import { verifyToken, hasUsers } from '$lib/server/auth.js';

/** Paths that do not require authentication.
 * /api/setup/* must be public because the setup wizard (which is public)
 * makes fetch() calls to these endpoints for NIC discovery, bridge config,
 * and storage status. Without this, the auth middleware redirects the API
 * calls to /setup (HTML), which breaks JSON parsing in the browser.
 */
const PUBLIC_PATHS = ['/login', '/setup', '/api/auth', '/api/setup'];

function isPublicPath(pathname: string): boolean {
	return PUBLIC_PATHS.some((p) => pathname.startsWith(p));
}

export const handle: Handle = async ({ event, resolve }) => {
	const { pathname } = event.url;

	// --- Parse JWT from cookie ---
	const token = event.cookies.get('nettap_token');
	if (token) {
		const payload = verifyToken(token);
		if (payload) {
			event.locals.user = payload;
		}
	}

	// --- First-run redirect: if no users exist, force setup ---
	// Also skip redirect for /api/setup/* — the setup wizard's own API calls
	if (!pathname.startsWith('/setup') && !pathname.startsWith('/api/auth') && !pathname.startsWith('/api/setup')) {
		try {
			if (!hasUsers()) {
				throw redirect(302, '/setup');
			}
		} catch (e) {
			// Re-throw redirect responses
			if (e && typeof e === 'object' && 'status' in e) {
				throw e;
			}
			// If hasUsers() fails (e.g., no DATA_DIR), allow through
		}
	}

	// --- Auth guard: redirect to /login if not authenticated ---
	if (!isPublicPath(pathname) && !event.locals.user) {
		// Allow health endpoint without auth for Docker healthcheck
		if (pathname === '/api/health') {
			return resolve(event);
		}
		throw redirect(302, '/login');
	}

	// --- If authenticated user visits /login, redirect to dashboard ---
	if (pathname === '/login' && event.locals.user) {
		throw redirect(302, '/');
	}

	return resolve(event);
};
