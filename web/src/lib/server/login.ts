import { randomBytes } from 'crypto';
import { getUser, hashPassword, setupCodeMatches, verifyPassword, type User } from './auth.js';

// ----- Login throttling (CR-034) -----
// Shared by the login form action and POST /api/auth/login.

// Per client IP: every attempt counts, so one host can't queue argon2 jobs on the libuv pool.
const IP_MAX_ATTEMPTS = 5;
const IP_WINDOW_MS = 60_000;
// Per username: from the 5th failure, lock for 1 min, doubling each failure, capped at 15 min.
const USER_LOCK_AFTER = 5;
const USER_BASE_LOCK_MS = 60_000;
const USER_MAX_LOCK_MS = 15 * 60_000;
// Memory bound: each map holds at most this many keys; expired entries go first, then the oldest.
const MAX_ENTRIES = 10_000;
const MAX_USERNAME_KEY = 128;

interface IpEntry {
	count: number;
	resetAt: number;
}

interface UserEntry {
	failures: number;
	lockedUntil: number;
	resetAt: number;
}

const ipAttempts = new Map<string, IpEntry>();
const userFailures = new Map<string, UserEntry>();

export type LoginResult =
	| { ok: true; user: User }
	| { ok: false; status: 401 | 429; error: string; retryAfter?: number };

function remember<V extends { resetAt: number }>(
	map: Map<string, V>,
	key: string,
	value: V,
	now: number
): void {
	map.delete(key); // re-insert so Map order stays oldest-first
	if (map.size >= MAX_ENTRIES) {
		for (const [k, v] of map) if (v.resetAt <= now) map.delete(k);
	}
	if (map.size >= MAX_ENTRIES) map.delete(map.keys().next().value as string);
	map.set(key, value);
}

/** Count this attempt for the IP; returns ms to wait, or 0 if allowed. */
function takeIpAttempt(ip: string, now: number): number {
	const entry = ipAttempts.get(ip);
	if (!entry || entry.resetAt <= now) {
		remember(ipAttempts, ip, { count: 1, resetAt: now + IP_WINDOW_MS }, now);
		return 0;
	}
	if (entry.count >= IP_MAX_ATTEMPTS) return entry.resetAt - now;
	ipAttempts.set(ip, { ...entry, count: entry.count + 1 });
	return 0;
}

function userLockRemaining(key: string, now: number): number {
	const entry = userFailures.get(key);
	return entry && entry.lockedUntil > now ? entry.lockedUntil - now : 0;
}

function recordFailure(key: string, now: number): void {
	const prev = userFailures.get(key);
	const failures = (prev && prev.resetAt > now ? prev.failures : 0) + 1;
	const lockMs =
		failures < USER_LOCK_AFTER
			? 0
			: Math.min(USER_BASE_LOCK_MS * 2 ** (failures - USER_LOCK_AFTER), USER_MAX_LOCK_MS);
	// Failures are forgotten 15 min after the lock ends with no new failure.
	const lockedUntil = now + lockMs;
	remember(userFailures, key, { failures, lockedUntil, resetAt: lockedUntil + USER_MAX_LOCK_MS }, now);
}

// OLD CODE: tooMany(ms, what = 'login attempts') (NET-229 follow-up: the setup code has its own limit
// again, so only the login uses this reply)
function tooMany(ms: number): LoginResult {
	const secs = Math.ceil(ms / 1000);
	const mins = Math.ceil(secs / 60);
	const wait = secs <= 60 ? `${secs} second${secs === 1 ? '' : 's'}` : `${mins} minutes`;
	return {
		ok: false,
		status: 429,
		retryAfter: secs,
		error: `Too many login attempts. Please wait ${wait} and try again.`,
	};
}

let dummyHashPromise: Promise<string> | null = null;

function dummyHash(): Promise<string> {
	dummyHashPromise ??= hashPassword(randomBytes(32).toString('hex')).catch((err) => {
		dummyHashPromise = null;
		throw err;
	});
	return dummyHashPromise;
}

/**
 * Check a username and password, throttled per client IP and per username.
 * Unknown usernames are tracked and hashed like real ones, so neither the
 * lockout nor the response time reveals which usernames exist.
 */
export async function attemptLogin(
	ip: string,
	username: string,
	password: string
): Promise<LoginResult> {
	const now = Date.now();
	const key = username.slice(0, MAX_USERNAME_KEY);

	const wait = takeIpAttempt(ip, now) || userLockRemaining(key, now);
	if (wait > 0) return tooMany(wait);

	const user = getUser(username);
	const valid = await verifyPassword(password, user?.passwordHash ?? (await dummyHash()));
	if (!user || !valid) {
		recordFailure(key, Date.now());
		return { ok: false, status: 401, error: 'Invalid username or password.' };
	}

	userFailures.delete(key);
	return { ok: true, user };
}

export type SetupCodeResult = { ok: true } | { ok: false; status: 400 | 429; error: string };

// OLD CODE START — review L4 (NET-229 follow-up): it shared the login's per-address bucket, and
// behind Docker's IPv6 proxy every client can arrive from one address, so one LAN host could lock
// the owner out of the setup code and the login (or the limit meant nothing)
// /**
//  * A13 (NET-229): check the first-run setup code. Every try takes one from the same per-IP budget as
//  * a login, so guessing the ~59-bit code is no faster than guessing a password.
//  */
// export function checkSetupCode(ip: string, code: string): SetupCodeResult {
// 	const wait = takeIpAttempt(ip, Date.now());
// 	if (wait > 0) {
// 		const { status, error } = tooMany(wait, 'attempts');
// 		return { ok: false, status, error };
// 	}
// 	if (setupCodeMatches(code)) return { ok: true };
// 	return {
// 		ok: false,
// 		status: 400,
// 		error: "That setup code isn't right. The installer printed it at the end; see below to read it again.",
// 	};
// }
// OLD CODE END

// OLD CODE START — Codex review: refusing every code after 50 failures let any LAN client keep the
// owner from setting up (send 50 wrong codes after each restart)
// // The setup code's own limit: ~59 bits make guessing hopeless, so a cap on wrong codes overall
// // stops a patient guesser. Restarting nettap-web lifts it (the owner can, an attacker can't).
// const SETUP_CODE_MAX_FAILURES = 50;
// let setupCodeFailures = 0;
//
// /** A13 (NET-229): check the first-run setup code, against its own limit (not the login's). */
// export function checkSetupCode(code: string): SetupCodeResult {
// 	if (setupCodeFailures >= SETUP_CODE_MAX_FAILURES) {
// 		return {
// 			ok: false,
// 			status: 429,
// 			error: 'Too many wrong setup codes. To try again, restart the web app on the NetTap box: sudo docker restart nettap-web',
// 		};
// 	}
// 	if (setupCodeMatches(code)) return { ok: true };
// 	setupCodeFailures++;
// 	if (setupCodeFailures === SETUP_CODE_MAX_FAILURES) {
// 		console.warn(`Setup code: ${SETUP_CODE_MAX_FAILURES} wrong codes; refused until nettap-web restarts.`);
// 	}
// 	return {
// 		ok: false,
// 		status: 400,
// 		error: "That setup code isn't right. The installer printed it at the end; see below to read it again.",
// 	};
// }
// OLD CODE END

// The setup code's own limit, apart from the login's. Its ~59 bits are the protection: the right
// code always works, so nobody can lock the owner out. Past 50 wrong codes overall (any address),
// wrong ones get 429 and one log line, which tells the owner something is guessing.
const SETUP_CODE_WARN_AFTER = 50;
let setupCodeFailures = 0;

/** A13 (NET-229): check the first-run setup code, against its own limit (not the login's). */
export function checkSetupCode(code: string): SetupCodeResult {
	if (setupCodeMatches(code)) return { ok: true };
	setupCodeFailures++;
	if (setupCodeFailures === SETUP_CODE_WARN_AFTER) {
		console.warn(`Setup code: ${SETUP_CODE_WARN_AFTER} wrong codes so far; something may be guessing it.`);
	}
	if (setupCodeFailures >= SETUP_CODE_WARN_AFTER) {
		return {
			ok: false,
			status: 429,
			error: "Too many wrong setup codes have been tried. Read the code again on the NetTap box: sudo docker exec nettap-web cat /var/lib/nettap-web/setup-code",
		};
	}
	return {
		ok: false,
		status: 400,
		error: "That setup code isn't right. The installer printed it at the end; see below to read it again.",
	};
}

// ----- Where to go after signing in (NET-198) -----

const NEXT_BASE = 'http://local.invalid';

/** One leading slash, so not `//host` or `/\host`, which a browser reads as another site. */
const isLocalPath = (path: string) => path.startsWith('/') && !path.startsWith('//') && !path.startsWith('/\\');

/**
 * The page to open after a sign-in: the `next` query value when it is a same-origin path, else `/`.
 * The result is the URL parser's own form, so tabs and line breaks are gone and the value is safe in
 * a Location header. That form is checked again: `/a/..//evil.com` and `/%2e//evil.com` parse as
 * same-origin but normalise to `//evil.com`, which would leave the site.
 */
export function safeNextPath(raw: string | null | undefined): string {
	if (!raw || !isLocalPath(raw)) return '/';
	try {
		const url = new URL(raw, NEXT_BASE);
		const out = url.pathname + url.search;
		return url.origin === NEXT_BASE && isLocalPath(out) && new URL(out, NEXT_BASE).origin === NEXT_BASE ? out : '/';
	} catch {
		return '/';
	}
}
