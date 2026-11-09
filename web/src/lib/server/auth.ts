import * as argon2 from 'argon2';
import jwt from 'jsonwebtoken';
import { readFileSync, writeFileSync, mkdirSync, existsSync, renameSync, rmSync } from 'fs';
import { dirname } from 'path';
import { createHash, createHmac, randomBytes, randomInt, timingSafeEqual } from 'crypto';
import { DATA_DIR } from './data-dir.js';

// ----- Constants -----

// OLD CODE START — hardcoded JWT secret, insecure for open-source
// const JWT_SECRET = process.env.JWT_SECRET || 'nettap-dev-secret-change-in-production';
// OLD CODE END
const TOKEN_EXPIRY = '24h';
// OLD CODE: const DATA_DIR = process.env.DATA_DIR || '/var/lib/nettap-web'; (review L4: shared with notifications.ts)
const USERS_FILE = `${DATA_DIR}/users.json`;

// ----- JWT Secret (auto-generated, file-persisted) -----

let _cachedSecret: string | null = null;

function getJwtSecret(): string {
	if (_cachedSecret) return _cachedSecret;

	// Environment variable takes precedence (for manual override)
	if (process.env.JWT_SECRET) {
		_cachedSecret = process.env.JWT_SECRET;
		return _cachedSecret;
	}

	const secretFile = `${DATA_DIR}/jwt-secret.txt`;

	// Try to read from persisted file
	try {
		if (existsSync(secretFile)) {
			_cachedSecret = readFileSync(secretFile, 'utf-8').trim();
			if (_cachedSecret) return _cachedSecret;
		}
	} catch {
		/* fall through to generation */
	}

	// Generate new secret on first run
	_cachedSecret = randomBytes(64).toString('hex');
	ensureDataDir();
	writeFileSync(secretFile, _cachedSecret, { mode: 0o600 });
	return _cachedSecret;
}

// ----- Types -----

export interface User {
	username: string;
	passwordHash: string;
	role: string;
	createdAt: string;
	updatedAt: string;
}

export interface TokenPayload {
	username: string;
	role: string;
}

interface UsersStore {
	users: User[];
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

export function generateToken(payload: TokenPayload): string {
	return jwt.sign(payload, getJwtSecret(), { expiresIn: TOKEN_EXPIRY });
}

export function verifyToken(token: string): TokenPayload | null {
	try {
		const decoded = jwt.verify(token, getJwtSecret()) as jwt.JwtPayload & TokenPayload;
		return { username: decoded.username, role: decoded.role };
	} catch {
		return null;
	}
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
	constructor(reason: string) {
		super(`User store unusable: ${reason}`);
		this.name = 'UserStoreError';
	}
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
	return parsed as UsersStore;
}

function writeUsers(store: UsersStore): void {
	ensureDataDir();
	const dir = dirname(USERS_FILE);
	if (!existsSync(dir)) {
		mkdirSync(dir, { recursive: true });
	}
	// OLD CODE START — wrote in place; a crash mid-write left a corrupt store (2026-10-29)
	// writeFileSync(USERS_FILE, JSON.stringify(store, null, 2), 'utf-8');
	// OLD CODE END
	// Write then rename so a crash never leaves a half-written (now fail-closed) store.
	const tmpFile = `${USERS_FILE}.tmp`;
	writeFileSync(tmpFile, JSON.stringify(store, null, 2), 'utf-8');
	renameSync(tmpFile, USERS_FILE);
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

export async function updatePassword(username: string, newPassword: string): Promise<void> {
	const store = readUsers();
	const user = store.users.find((u) => u.username === username);

	if (!user) {
		throw new Error(`User "${username}" not found`);
	}

	user.passwordHash = await hashPassword(newPassword);
	user.updatedAt = new Date().toISOString();
	writeUsers(store);
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
