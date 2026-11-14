import type { Handle, ServerInit } from '@sveltejs/kit';
import { json, redirect } from '@sveltejs/kit';
import { verifyToken, hasUsers, ensureSetupCode } from '$lib/server/auth.js';
import { hasSetupCookie } from '$lib/server/middleware.js';
import { SIGN_IN_FIRST } from '$lib/auth-errors.js';

/** A13 (NET-229): make the first-run setup code at start, so the installer can print it. The code
 * itself is never logged; reading it needs a shell on the box. */
export const init: ServerInit = () => {
	try {
		if (ensureSetupCode()) {
			console.info(
				'First run: the setup wizard asks for a setup code. Read it with: sudo docker exec nettap-web cat /var/lib/nettap-web/setup-code'
			);
		}
	} catch (err) {
		console.error('First run: could not make the setup code:', err);
	}
};

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

// OLD CODE START — NET-193: the tools and lookups answered without a login, so anyone on the
// LAN could make the appliance ping, trace and resolve hosts and read device names (2026-11-07)
// /** Paths that never require authentication.
//  * /api/tools/* and /api/lookup/* are public so tools pages work without auth.
//  */
// const PUBLIC_PATHS = ['/login', '/api/auth', '/api/tools', '/api/lookup', '/tools', '/lookup'];
// OLD CODE END

/** Paths that never require authentication: the sign-in page and the three auth routes, matched
 * exactly. Nothing below them: a path no auth route handles (`/api/auth/me/x`, `/api/auth/other`)
 * falls through to the catch-all proxy, which forwards it to the daemon with the daemon token. */
const PUBLIC_PATHS = new Set(['/login', '/api/auth/login', '/api/auth/logout', '/api/auth/me']);

/** Paths that are public only until the first admin exists.
 * The setup wizard (/setup, /api/setup/*) runs before any account exists. Afterwards
 * these paths reconfigure the appliance, so they need a session like every other route.
 * The setup action signs the new admin in, so the rest of the wizard and Go Live keep
 * working. Before that, everything but /setup needs the setup cookie (NET-229 follow-up).
 * NET-277: /go-live is not here. Its capture-mode call needs a session, so until the first
 * admin exists it goes to /setup like every other page. /api/bridge/* was Go Live's and has no
 * caller before the first admin now; it still needs the setup cookie then.
 */
// OLD CODE START — NET-277: Go Live opened on the setup cookie, then its capture-mode call got 401
// const FIRST_RUN_PATHS = ['/setup', '/api/setup', '/api/bridge', '/go-live'];
// OLD CODE END
const FIRST_RUN_PATHS = ['/setup', '/api/setup', '/api/bridge'];

/** The calls the wizard makes before its Account step, matched by exact
 * method and path (not prefix).
 * OLD CODE START — NET-229: no longer true once the account needs the setup code
 * Opening them before the first admin exists adds nothing: whoever can reach the device then can claim it anyway.
 * OLD CODE END
 * OLD CODE START — NET-229 follow-up: they now need the setup cookie too
 * They stay open until the first admin exists. The setup code (A13) guards the admin account, so
 * a LAN host can no longer claim the box, but it can still call these until the owner finishes setup.
 * OLD CODE END
 * Until the first admin exists they answer a browser that typed the setup code on the Welcome step
 * (the setup cookie), like the wizard's /api paths above.
 */
const FIRST_RUN_REQUESTS = new Set([
	'GET /api/settings/excluded-ips',
	'POST /api/integrations/unifi/configure',
	'POST /api/integrations/unifi/test',
]);

/** `pathname` is `base` or below it: whole path segments, so '/login' never opens '/loginx'. */
function isUnder(pathname: string, base: string): boolean {
	return pathname === base || pathname.startsWith(`${base}/`);
}

// OLD CODE START — NET-193: a bare prefix, so a future '/api/auth-tokens' or '/setupx' would be open too
// function isPublicPath(pathname: string): boolean {
// 	return PUBLIC_PATHS.some((p) => pathname.startsWith(p));
// }
//
// function isFirstRunPath(method: string, pathname: string): boolean {
// 	return (
// 		FIRST_RUN_PATHS.some((p) => pathname.startsWith(p)) ||
// 		FIRST_RUN_REQUESTS.has(`${method} ${pathname}`)
// 	);
// }
// OLD CODE END
function isPublicPath(pathname: string): boolean {
	return PUBLIC_PATHS.has(pathname);
}

function isFirstRunPath(method: string, pathname: string): boolean {
	return (
		FIRST_RUN_PATHS.some((p) => isUnder(pathname, p)) ||
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

/** The reply to an API or remote-function call with no session: JSON the caller can check.
 * The shell's ping check (routes/+layout.svelte) matches this error text to send the user to sign in. */
function unauthorised(): Response {
	// OLD CODE: return json({ error: 'Sign in first' }, { status: 401 }); (NET-198: one constant for the hook and the shell)
	return json({ error: SIGN_IN_FIRST }, { status: 401 });
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

	// A remote-function call's pathname comes from the client's x-sveltekit-pathname header, so
	// no path rule may open it: without a session it is refused (the app has no remote functions yet)
	if (event.isRemoteRequest && !event.locals.user) {
		// OLD CODE START — NET-197: /api calls get the same reply now, so it lives in unauthorised()
		// return new Response(JSON.stringify({ error: 'Sign in first' }), {
		// 	status: 401,
		// 	headers: { 'content-type': 'application/json' },
		// });
		// OLD CODE END
		return unauthorised();
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
		// NET-257: SameSite=lax lets another site's link (or one opened from a mail or chat app, sent as
		// "none") reach the daemon with the owner's cookie, e.g. to hold the PCAP download slot. Every /api
		// route, by the route SvelteKit matched, so an encoded path (/%61pi/…) can't slip past. NetTap's own
		// pages only send same-origin; no header is a script, which no web page can drive.
		const site = event.request.headers.get('sec-fetch-site');
		if (site && site !== 'same-origin' && event.route.id?.startsWith('/api/')) {
			return json({ error: 'Open this from NetTap itself.' }, { status: 403 });
		}

		// OLD CODE: // --- First run: only the wizard and Go Live are open; everything else goes to setup --- (NET-277)
		// --- First run: only the wizard is open; everything else goes to setup ---
		const firstRun = isFirstRun();
		// OLD CODE START — NET-229 follow-up: the wizard's API calls answered anyone on the LAN until setup ended
		// if (firstRun && isFirstRunPath(event.request.method, pathname)) {
		// 	return resolve(event);
		// }
		// OLD CODE END
		// OLD CODE START — review: /go-live stayed open without the code; only /setup needs to be
		// if (firstRun && isFirstRunPath(event.request.method, pathname)) {
		// 	// The pages stay open so the code can be typed; their API calls need the setup cookie
		// 	if (isUnder(pathname, '/api') && !hasSetupCookie(event)) {
		// 		return json({ error: 'Enter the setup code first.' }, { status: 401 });
		// 	}
		// 	return resolve(event);
		// }
		// OLD CODE END
		if (firstRun && isFirstRunPath(event.request.method, pathname)) {
			// /setup stays open so the code can be typed there; the rest needs the setup cookie.
			// Only /setup is a first-run page now; the redirect keeps any page added later fail-closed.
			if (!isUnder(pathname, '/setup') && !hasSetupCookie(event)) {
				if (isUnder(pathname, '/api')) {
					return json({ error: 'Enter the setup code first.' }, { status: 401 });
				}
				throw redirect(302, '/setup');
			}
			return resolve(event);
		}
		// OLD CODE START — NET-197 review: an /api address opened as a page (form post, new tab) got raw
		// JSON, and an API call during first run with a leftover valid cookie still got the setup redirect
		// // NET-197: an API call gets 401 JSON, not the redirects below: fetch follows a redirect,
		// // so the login or setup page's HTML reached the caller as a 200 and looked like success
		// if (!event.locals.user && isUnder(pathname, '/api')) {
		// 	return unauthorised();
		// }
		// OLD CODE END
		// NET-197: a script's call to /api (fetch, EventSource, <a download>) gets 401 JSON, not the
		// redirects below: fetch follows a redirect, so the login or setup page's HTML reached it as a 200.
		// An /api address opened as a page keeps the redirect. The browser sets Sec-Fetch-Dest and page
		// script can't, and it only chooses between two refusals.
		const openedAsPage = event.request.headers.get('sec-fetch-dest') === 'document';
		if ((firstRun || !event.locals.user) && isUnder(pathname, '/api') && !openedAsPage) {
			return unauthorised();
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
