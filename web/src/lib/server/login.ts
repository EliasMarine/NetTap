import { randomBytes } from 'crypto';
import { getUser, hashPassword, verifyPassword, type User } from './auth.js';

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
