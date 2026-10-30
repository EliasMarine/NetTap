import type { Handle } from '@sveltejs/kit';
import { redirect } from '@sveltejs/kit';
import { verifyToken, hasUsers } from '$lib/server/auth.js';

// OLD CODE START — setup, bridge and go-live stayed public forever, so anyone on
// the LAN could reconfigure or tear down the bridge after setup (2026-10-29)
// /** Paths that do not require authentication.
//  * /api/setup/* must be public because the setup wizard (which is public)
//  * makes fetch() calls to these endpoints for NIC discovery, bridge config,
//  * and storage status. /api/bridge/* and /go-live are public because the
//  * Go Live page is part of the initial deployment flow (wizard → go-live)
//  * and needs bridge readiness/health data before the user has logged in.
//  * /api/tools/* and /api/lookup/* are public so tools pages work without auth.
//  */
// const PUBLIC_PATHS = ['/login', '/setup', '/api/auth', '/api/setup', '/api/bridge', '/go-live', '/api/tools', '/api/lookup', '/tools', '/lookup'];
// OLD CODE END

/** Paths that never require authentication.
 * /api/tools/* and /api/lookup/* are public so tools pages work without auth.
 */
const PUBLIC_PATHS = ['/login', '/api/auth', '/api/tools', '/api/lookup', '/tools', '/lookup'];

/** Paths that are public only until the first admin exists.
 * The setup wizard (/setup, /api/setup/*) and Go Live (/go-live, /api/bridge/*)
 * run before any account exists. Afterwards they reconfigure the appliance, so
 * they need a session like every other route. The setup action signs the new
 * admin in, so the rest of the wizard and Go Live keep working.
 */
const FIRST_RUN_PATHS = ['/setup', '/api/setup', '/api/bridge', '/go-live'];

/** The calls the wizard makes before its Account step, matched by exact
 * method and path (not prefix). Opening them before the first admin exists
 * adds nothing: whoever can reach the device then can claim it anyway.
 */
const FIRST_RUN_REQUESTS = new Set([
	'GET /api/settings/excluded-ips',
	'POST /api/integrations/unifi/configure',
	'POST /api/integrations/unifi/test',
]);

function isPublicPath(pathname: string): boolean {
	return PUBLIC_PATHS.some((p) => pathname.startsWith(p));
}

function isFirstRunPath(method: string, pathname: string): boolean {
	return (
		FIRST_RUN_PATHS.some((p) => pathname.startsWith(p)) ||
		FIRST_RUN_REQUESTS.has(`${method} ${pathname}`)
	);
}

/** True only for a readable, empty user store. A damaged store never reopens first-run. */
function isFirstRun(): boolean {
	try {
		return !hasUsers();
	} catch {
		return false;
	}
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

	// OLD CODE START — replaced by the first-run gate below (2026-10-29)
	// // --- First-run redirect: if no users exist, force setup ---
	// // Skip for public paths (setup wizard, bridge API, go-live) and health endpoint
	// if (!isPublicPath(pathname) && pathname !== '/api/health') {
	// 	try {
	// 		if (!hasUsers()) {
	// 			throw redirect(302, '/setup');
	// 		}
	// 	} catch (e) {
	// 		// Re-throw redirect responses
	// 		if (e && typeof e === 'object' && 'status' in e) {
	// 			throw e;
	// 		}
	// 		// If hasUsers() fails (e.g., no DATA_DIR), allow through
	// 	}
	// }
	//
	// // --- Auth guard: redirect to /login if not authenticated ---
	// if (!isPublicPath(pathname) && !event.locals.user) {
	// 	// Allow health endpoint without auth for Docker healthcheck
	// 	if (pathname === '/api/health') {
	// 		return resolve(event);
	// 	}
	// 	throw redirect(302, '/login');
	// }
	// OLD CODE END

	// Allow health endpoint without auth for Docker healthcheck
	if (pathname === '/api/health') {
		return resolve(event);
	}

	if (!isPublicPath(pathname)) {
		// --- First run: only the wizard and Go Live are open; everything else goes to setup ---
		const firstRun = isFirstRun();
		if (firstRun && isFirstRunPath(event.request.method, pathname)) {
			return resolve(event);
		}
		if (firstRun) {
			throw redirect(302, '/setup');
		}

		// --- Auth guard: redirect to /login if not authenticated ---
		if (!event.locals.user) {
			throw redirect(302, '/login');
		}
	}

	// --- If authenticated user visits /login, redirect to dashboard ---
	if (pathname === '/login' && event.locals.user) {
		throw redirect(302, '/');
	}

	return resolve(event);
};
