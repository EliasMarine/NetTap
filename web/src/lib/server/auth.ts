import * as argon2 from 'argon2';
import jwt from 'jsonwebtoken';
import { readFileSync, writeFileSync, mkdirSync, existsSync, renameSync, rmSync } from 'fs';
import { dirname } from 'path';
import { createHash, createHmac, randomInt, timingSafeEqual } from 'crypto';
import { DATA_DIR } from './data-dir.js';
import { writeFileDurably } from './durable-write.js';
import { getJwtSecret } from './session-keys.js';

export { initSessionKeys } from './session-keys.js';

// ----- Constants -----

// OLD CODE START — hardcoded JWT secret, insecure for open-source
// const JWT_SECRET = process.env.JWT_SECRET || 'nettap-dev-secret-change-in-production';
// OLD CODE END
const TOKEN_EXPIRY = '24h';
// OLD CODE: const DATA_DIR = process.env.DATA_DIR || '/var/lib/nettap-web'; (review L4: shared with notifications.ts)
const USERS_FILE = `${DATA_DIR}/users.json`;

// ----- JWT Secret -----

// OLD CODE START — NET-358: signed with JWT_SECRET or jwt-secret.txt, which every older build also
// trusts, so a downgrade would accept a session a password change had ended. The key now comes from
// session-keys.ts (jwt-secret-v2.txt), and jwt-secret.txt is replaced at every start.
// let _cachedSecret: string | null = null;
//
// function getJwtSecret(): string {
// 	if (_cachedSecret) return _cachedSecret;
//
// 	// Environment variable takes precedence (for manual override)
// 	if (process.env.JWT_SECRET) {
// 		_cachedSecret = process.env.JWT_SECRET;
// 		return _cachedSecret;
// 	}
//
// 	const secretFile = `${DATA_DIR}/jwt-secret.txt`;
//
// 	// Try to read from persisted file
// 	try {
// 		if (existsSync(secretFile)) {
// 			_cachedSecret = readFileSync(secretFile, 'utf-8').trim();
// 			if (_cachedSecret) return _cachedSecret;
// 		}
// 	} catch {
// 		/* fall through to generation */
// 	}
//
// 	// Generate new secret on first run
// 	_cachedSecret = randomBytes(64).toString('hex');
// 	ensureDataDir();
// 	writeFileSync(secretFile, _cachedSecret, { mode: 0o600 });
// 	return _cachedSecret;
// }
// OLD CODE END

// ----- Types -----

export interface User {
	username: string;
	passwordHash: string;
	role: string;
	createdAt: string;
	updatedAt: string;
}

/** Who a valid session belongs to: the stored username and role. */
export interface TokenPayload {
	username: string;
	role: string;
}

/** What a session token says (NET-358): `pwd` names the password it was issued against. */
interface SessionClaims extends TokenPayload {
	pwd: string;
}

interface UsersStore {
	users: User[];
}

// ----- Password rules -----

/** NET-358: stops a megabyte reaching argon2. Also caps the current password in Settings › Account. */
// OLD CODE: const PASSWORD_MAX_LENGTH = 1024; (NET-358 review: exported for the change endpoint's current-password cap)
export const PASSWORD_MAX_LENGTH = 1024;

/** The first rule `password` breaks, as the sentence to show, or null when it is acceptable. Shared by setup and Settings › Account. */
export function passwordProblem(password: string): string | null {
	if (password.length < 8) return 'Password must be at least 8 characters.';
	if (password.length > PASSWORD_MAX_LENGTH) return 'Password must be at most 1,024 characters.';
	if (!/[A-Z]/.test(password)) return 'Password must contain at least one uppercase letter.';
	if (!/[a-z]/.test(password)) return 'Password must contain at least one lowercase letter.';
	if (!/[0-9]/.test(password)) return 'Password must contain at least one number.';
	return null;
}

// ----- Password Hashing -----

export async function hashPassword(password: string): Promise<string> {
	return argon2.hash(password, {
		type: argon2.argon2id,
		memoryCost: 65536,
		timeCost: 3,
		parallelism: 4,
	});
}

export async function verifyPassword(password: string, hash: string): Promise<boolean> {
	try {
		return await argon2.verify(hash, password);
	} catch {
		return false;
	}
}

// ----- JWT -----

/** A short, one-way name for a password hash, so a session can say which password it was issued against. */
export function passwordStamp(hash: string): string {
	return createHash('sha256').update(hash).digest('base64url').slice(0, 22);
}

// OLD CODE START — NET-358: signed its argument verbatim, so a caller passing a whole User would have
// put the argon2 hash in a cookie, and a session outlived a password change
// export function generateToken(payload: TokenPayload): string {
// 	return jwt.sign(payload, getJwtSecret(), { expiresIn: TOKEN_EXPIRY });
// }
//
// export function verifyToken(token: string): TokenPayload | null {
// 	try {
// 		const decoded = jwt.verify(token, getJwtSecret()) as jwt.JwtPayload & TokenPayload;
// 		return { username: decoded.username, role: decoded.role };
// 	} catch {
// 		return null;
// 	}
// }
// OLD CODE END

/** Signs exactly username, role and the password stamp: never the argument itself, which may be a whole User. */
export function generateToken(user: Pick<User, 'username' | 'role' | 'passwordHash'>): string {
	const claims: SessionClaims = { username: user.username, role: user.role, pwd: passwordStamp(user.passwordHash) };
	return jwt.sign(claims, getJwtSecret(), { algorithm: 'HS256', expiresIn: TOKEN_EXPIRY });
}

const STORE_REFUSAL_LOG_MS = 60_000;
let lastStoreRefusalLog = -Infinity;

/** A damaged store must show in the log, not look like expired sessions; once a minute at most. */
function logStoreRefusal(err: UserStoreError): void {
	const now = Date.now();
	if (now - lastStoreRefusalLog < STORE_REFUSAL_LOG_MS) return;
	lastStoreRefusalLog = now;
	console.error(`Sessions refused: the user store is unusable (${err.reason})`);
}

function storedUser(username: string): User | undefined {
	try {
		return getUser(username);
	} catch (err) {
		if (!(err instanceof UserStoreError)) throw err;
		logStoreRefusal(err);
		return undefined;
	}
}

/**
 * The session's user, or null. A valid signature isn't enough: the user must still exist and the
 * token's password stamp must match the stored hash, so a password change ends every older session.
 * A token without a stamp (from before NET-358) is refused. The role is the stored one.
 * shortcut: reads users.json (a few hundred bytes) on every request; cache by mtime if the store or request rate grows.
 */
export function verifyToken(token: string): TokenPayload | null {
	const key = getJwtSecret();
	let claims: jwt.JwtPayload;
	try {
		const decoded = jwt.verify(token, key, { algorithms: ['HS256'] });
		if (typeof decoded === 'string') return null;
		claims = decoded;
	} catch {
		return null;
	}
	if (typeof claims.username !== 'string' || typeof claims.pwd !== 'string') return null;
	const user = storedUser(claims.username);
	if (!user || !sameText(claims.pwd, passwordStamp(user.passwordHash))) return null;
	return { username: user.username, role: user.role };
}

// ----- User Storage -----

function ensureDataDir(): void {
	if (!existsSync(DATA_DIR)) {
		try {
			mkdirSync(DATA_DIR, { recursive: true });
		} catch {
			// In development, DATA_DIR might not be writable; silently continue
		}
	}
}

/** The users file exists but cannot be read, parsed or understood. */
export class UserStoreError extends Error {
	readonly reason: string;

	constructor(reason: string) {
		super(`User store unusable: ${reason}`);
		this.name = 'UserStoreError';
		this.reason = reason;
	}
}

/** NET-358: the stored role is trusted for every session, so each record must have its fields. */
function isUserRecord(entry: unknown): boolean {
	if (typeof entry !== 'object' || entry === null) return false;
	const { username, passwordHash, role } = entry as Record<string, unknown>;
	return [username, passwordHash, role].every((field) => typeof field === 'string' && field !== '');
}

// OLD CODE START — any read/parse failure looked like "no users", so a damaged
// store reopened first-run setup and createUser could overwrite it (2026-10-29)
// function readUsers(): UsersStore {
// 	try {
// 		const data = readFileSync(USERS_FILE, 'utf-8');
// 		return JSON.parse(data) as UsersStore;
// 	} catch {
// 		return { users: [] };
// 	}
// }
// OLD CODE END

/**
 * Only a missing file means "no users yet". Anything else throws
 * UserStoreError so callers fail closed instead of reopening first-run.
 */
function readUsers(): UsersStore {
	let data: string;
	try {
		data = readFileSync(USERS_FILE, 'utf-8');
	} catch (err) {
		const code = (err as NodeJS.ErrnoException).code;
		if (code === 'ENOENT') return { users: [] };
		throw new UserStoreError(code ?? 'unreadable');
	}
	let parsed: unknown;
	try {
		parsed = JSON.parse(data);
	} catch {
		throw new UserStoreError('invalid JSON');
	}
	if (!Array.isArray((parsed as Partial<UsersStore> | null)?.users)) {
		throw new UserStoreError('missing users array');
	}
	if (!(parsed as UsersStore).users.every(isUserRecord)) {
		throw new UserStoreError('malformed user record');
	}
	return parsed as UsersStore;
}

/**
 * Replace the store, 0600 and fsynced (NET-358). Throws when nothing changed; `durable: false` when
 * the new store is live but its folder fsync failed, so it may not survive a power cut.
 */
function writeUsers(store: UsersStore): { durable: boolean } {
	ensureDataDir();
	const dir = dirname(USERS_FILE);
	if (!existsSync(dir)) {
		mkdirSync(dir, { recursive: true });
	}
	// OLD CODE START — wrote in place; a crash mid-write left a corrupt store (2026-10-29)
	// writeFileSync(USERS_FILE, JSON.stringify(store, null, 2), 'utf-8');
	// OLD CODE END
	// OLD CODE START — NET-358: no fsync and the process's default mode, so a power cut after a password
	// change could bring the old password back, and the store could end up readable by others
	// // Write then rename so a crash never leaves a half-written (now fail-closed) store.
	// const tmpFile = `${USERS_FILE}.tmp`;
	// writeFileSync(tmpFile, JSON.stringify(store, null, 2), 'utf-8');
	// renameSync(tmpFile, USERS_FILE);
	// OLD CODE END
	return writeFileDurably(USERS_FILE, JSON.stringify(store, null, 2));
}

export function getUser(username: string): User | undefined {
	const store = readUsers();
	return store.users.find((u) => u.username === username);
}

export async function createUser(
	username: string,
	password: string,
	role: string = 'admin'
): Promise<User> {
	const store = readUsers();

	if (store.users.find((u) => u.username === username)) {
		throw new Error(`User "${username}" already exists`);
	}

	const now = new Date().toISOString();
	const user: User = {
		username,
		passwordHash: await hashPassword(password),
		role,
		createdAt: now,
		updatedAt: now,
	};

	store.users.push(user);
	writeUsers(store);
	return user;
}

/** The first admin already exists (another setup request won the race). */
export class SetupAlreadyComplete extends Error {
	constructor() {
		super('Setup is already complete.');
		this.name = 'SetupAlreadyComplete';
	}
}

// One Node process serves every request, so a promise chain serializes setup.
let firstAdminLock: Promise<unknown> = Promise.resolve();

/**
 * Create the first admin, or throw SetupAlreadyComplete if any user exists.
 * Serialized and re-checked after the slow password hash, so two concurrent
 * setup requests can never both create an admin.
 */
export function createFirstAdmin(username: string, password: string): Promise<User> {
	const attempt = firstAdminLock.then(async () => {
		const passwordHash = await hashPassword(password);
		const store = readUsers();
		if (store.users.length > 0) {
			throw new SetupAlreadyComplete();
		}
		const now = new Date().toISOString();
		const user: User = { username, passwordHash, role: 'admin', createdAt: now, updatedAt: now };
		writeUsers({ users: [user] });
		return user;
	});
	firstAdminLock = attempt.catch(() => undefined);
	return attempt;
}

/** The stored password is no longer the one this change verified (another change won). */
export class PasswordChangedElsewhere extends Error {
	constructor() {
		super('The password was changed by another request.');
		this.name = 'PasswordChangedElsewhere';
	}
}

// OLD CODE START — NET-358: awaited the hash between reading and writing and updated by username only,
// so two changes that verified the same old password could both succeed; it also mutated the store
// export async function updatePassword(username: string, newPassword: string): Promise<void> {
// 	const store = readUsers();
// 	const user = store.users.find((u) => u.username === username);
//
// 	if (!user) {
// 		throw new Error(`User "${username}" not found`);
// 	}
//
// 	user.passwordHash = await hashPassword(newPassword);
// 	user.updatedAt = new Date().toISOString();
// 	writeUsers(store);
// }
// OLD CODE END

/**
 * Compare-and-swap: set `username`'s password only if the stored hash is still `expectedHash` (the
 * one the caller just verified), else throw PasswordChangedElsewhere. The hash is made first; from
 * the read to the write there is no `await`, so Node runs them as one step and two changes can't
 * both pass the check. `durable` is false when the store landed but its folder fsync failed.
 */
export async function updatePassword(
	username: string,
	expectedHash: string,
	newPassword: string
): Promise<{ user: User; durable: boolean }> {
	const passwordHash = await hashPassword(newPassword);
	const store = readUsers();
	const current = store.users.find((u) => u.username === username);
	if (!current) {
		throw new Error(`User "${username}" not found`);
	}
	if (current.passwordHash !== expectedHash) {
		throw new PasswordChangedElsewhere();
	}
	const user: User = { ...current, passwordHash, updatedAt: new Date().toISOString() };
	const { durable } = writeUsers({ ...store, users: store.users.map((u) => (u === current ? user : u)) });
	return { user, durable };
}

export function hasUsers(): boolean {
	const store = readUsers();
	return store.users.length > 0;
}

// ----- First-run setup code (A13, NET-229) -----

const SETUP_CODE_FILE = `${DATA_DIR}/setup-code`;
// No 0/O, 1/I/L or U, so it reads and types without mix-ups; 12 of 30 symbols is ~59 bits
const SETUP_CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTVWXYZ23456789';
const SETUP_CODE_SHAPE = new RegExp(`^[${SETUP_CODE_ALPHABET}]{12}$`);

/** Upper case, letters and digits only, so spaces, dashes and case never make a right code wrong. */
function normaliseSetupCode(code: string): string {
	return code.toUpperCase().replace(/[^A-Z0-9]/g, '');
}

/**
 * The one-time code that proves whoever creates the first admin can run commands on the box.
 * It lives in DATA_DIR, which only nettap-web mounts. Made while no user exists (a missing, short or
 * damaged file is replaced), removed once one does, and then this returns null. A damaged user
 * store throws, so first run stays closed.
 */
export function ensureSetupCode(): string | null {
	if (hasUsers()) {
		clearSetupCode();
		return null;
	}
	try {
		const stored = readFileSync(SETUP_CODE_FILE, 'utf-8').trim();
		if (SETUP_CODE_SHAPE.test(normaliseSetupCode(stored))) return stored;
	} catch (err) {
		if ((err as NodeJS.ErrnoException).code !== 'ENOENT') throw err;
	}
	const symbols = Array.from({ length: 12 }, () => SETUP_CODE_ALPHABET[randomInt(SETUP_CODE_ALPHABET.length)]);
	const code = [0, 4, 8].map((i) => symbols.slice(i, i + 4).join('')).join('-');
	ensureDataDir();
	// Write then rename, so a crash never leaves a short code behind
	const tmpFile = `${SETUP_CODE_FILE}.tmp`;
	writeFileSync(tmpFile, `${code}\n`, { mode: 0o600 });
	renameSync(tmpFile, SETUP_CODE_FILE);
	return code;
}

/** Constant-time string comparison (hashed first, so different lengths compare too). */
function sameText(a: string, b: string): boolean {
	const digest = (s: string) => createHash('sha256').update(s).digest();
	return timingSafeEqual(digest(a), digest(b));
}

/** Constant-time check of a typed code; false when it isn't 12 code symbols or setup is done. */
export function setupCodeMatches(input: string): boolean {
	const typed = normaliseSetupCode(input);
	if (!SETUP_CODE_SHAPE.test(typed)) return false;
	const code = ensureSetupCode();
	if (!code) return false;
	// OLD CODE START — NET-229 follow-up: the comparison moved to sameText(), shared with the setup cookie
	// const digest = (s: string) => createHash('sha256').update(s).digest();
	// return timingSafeEqual(digest(typed), digest(normaliseSetupCode(code)));
	// OLD CODE END
	return sameText(typed, normaliseSetupCode(code));
}

/**
 * The setup cookie's value: proof that this browser typed the current setup code on the Welcome
 * step, so the wizard's API calls may run (NET-229 follow-up). An HMAC, not a JWT, so it never
 * passes verifyToken as a session, and it stops matching once the code is gone or replaced.
 * Null once an admin exists.
 */
export function setupToken(): string | null {
	const code = ensureSetupCode();
	if (!code) return null;
	return createHmac('sha256', getJwtSecret()).update(`setup:${normaliseSetupCode(code)}`).digest('base64url');
}

export function setupTokenValid(token: string | undefined): boolean {
	const expected = token ? setupToken() : null;
	return expected !== null && sameText(token ?? '', expected);
}

export function clearSetupCode(): void {
	rmSync(SETUP_CODE_FILE, { force: true });
}
