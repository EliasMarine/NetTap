import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import jwt from 'jsonwebtoken';

/**
 * NET-358: the auth module against a real user store and real keys in a temp DATA_DIR (auth.test.ts
 * covers the rest with fs mocked): password rules, record validation, session claims, verifyToken and
 * the compare-and-swap password update.
 */

type Auth = typeof import('./auth.js');
type User = import('./auth.js').User;

let dataDir: string;
let auth: Auth;
let key: string;

const usersFile = () => join(dataDir, 'users.json');
const user = (username: string, passwordHash: string, role = 'admin'): User => ({
	username,
	passwordHash,
	role,
	createdAt: '2026-01-01T00:00:00.000Z',
	updatedAt: '2026-01-01T00:00:00.000Z',
});
const writeStore = (users: unknown[]) => writeFileSync(usersFile(), JSON.stringify({ users }));
const storedUsers = (): User[] => JSON.parse(readFileSync(usersFile(), 'utf-8')).users;

beforeEach(async () => {
	dataDir = mkdtempSync(join(tmpdir(), 'nettap-auth-store-'));
	vi.stubEnv('DATA_DIR', dataDir);
	vi.stubEnv('JWT_SECRET', '');
	vi.resetModules();
	auth = await import('./auth.js');
	auth.initSessionKeys();
	key = readFileSync(join(dataDir, 'jwt-secret-v2.txt'), 'utf-8');
});

afterEach(() => {
	vi.unstubAllEnvs();
	vi.restoreAllMocks();
	rmSync(dataDir, { recursive: true, force: true });
});

describe('passwordProblem', () => {
	it.each([
		['Ab1defg', 'Password must be at least 8 characters.'],
		[`Ab1${'x'.repeat(1022)}`, 'Password must be at most 1,024 characters.'],
		['abcdefg1', 'Password must contain at least one uppercase letter.'],
		['ABCDEFG1', 'Password must contain at least one lowercase letter.'],
		['Abcdefgh', 'Password must contain at least one number.'],
	])('refuses %s', (password, sentence) => {
		expect(auth.passwordProblem(password)).toBe(sentence);
	});

	it.each(['Abcdefg1', `Ab1${'x'.repeat(1021)}`])('accepts a password that keeps every rule (%#)', (password) => {
		expect(auth.passwordProblem(password)).toBeNull();
	});
});

describe('the user store', () => {
	it.each([
		['a null entry', [null]],
		['a string entry', ['admin']],
		['an entry with no password hash', [{ username: 'admin', role: 'admin' }]],
		['an entry with no role', [{ username: 'admin', passwordHash: 'x' }]],
		['an empty username', [user('', 'x')]],
		['a numeric role', [{ ...user('admin', 'x'), role: 1 }]],
		['one bad entry among good ones', [user('admin', 'x'), { username: 'other' }]],
	])('is unusable with %s', (_, users) => {
		writeStore(users);
		expect(() => auth.getUser('admin')).toThrow(auth.UserStoreError);
		expect(() => auth.hasUsers()).toThrow('malformed user record');
	});
});

describe('session tokens', () => {
	it('carry exactly username, role, the password stamp, iat and exp (no hash)', () => {
		const full = user('alice', '$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA');
		const claims = jwt.decode(auth.generateToken(full)) as Record<string, unknown>;

		expect(Object.keys(claims).sort()).toEqual(['exp', 'iat', 'pwd', 'role', 'username']);
		expect(claims).toMatchObject({ username: 'alice', role: 'admin', pwd: auth.passwordStamp(full.passwordHash) });
		expect(Number(claims.exp) - Number(claims.iat)).toBe(24 * 60 * 60);
		expect(JSON.stringify(claims)).not.toContain('argon2');
	});

	it('stamp a hash as 22 base64url characters, the same each time, different per hash', () => {
		const stamp = auth.passwordStamp('hash-1');
		expect(stamp).toMatch(/^[A-Za-z0-9_-]{22}$/);
		expect(auth.passwordStamp('hash-1')).toBe(stamp);
		expect(auth.passwordStamp('hash-2')).not.toBe(stamp);
	});
});

describe('verifyToken', () => {
	beforeEach(() => writeStore([user('admin', 'hash-1')]));

	it('accepts a token whose stamp matches the stored hash, with the stored role', () => {
		const token = auth.generateToken(user('admin', 'hash-1', 'viewer'));
		expect(auth.verifyToken(token)).toEqual({ username: 'admin', role: 'admin' });
	});

	it('refuses a token with no stamp (issued before NET-358)', () => {
		expect(auth.verifyToken(jwt.sign({ username: 'admin', role: 'admin' }, key))).toBeNull();
	});

	it('refuses a token for another password', () => {
		expect(auth.verifyToken(auth.generateToken(user('admin', 'hash-0')))).toBeNull();
	});

	it('refuses a stamp of the right length in characters but not in bytes, without throwing', () => {
		const stamp = auth.passwordStamp('hash-1');
		const wide = 'é' + stamp.slice(1); // 22 characters, 23 bytes
		expect(auth.verifyToken(jwt.sign({ username: 'admin', role: 'admin', pwd: wide }, key))).toBeNull();
		expect(auth.verifyToken(jwt.sign({ username: 'admin', role: 'admin', pwd: stamp.slice(1) }, key))).toBeNull();
	});

	it('refuses a token for an unknown user', () => {
		expect(auth.verifyToken(auth.generateToken(user('ghost', 'hash-1')))).toBeNull();
	});

	it('refuses a wrong signature, another algorithm and garbage', () => {
		const claims = { username: 'admin', role: 'admin', pwd: auth.passwordStamp('hash-1') };
		expect(auth.verifyToken(jwt.sign(claims, 'f'.repeat(128)))).toBeNull();
		expect(auth.verifyToken(jwt.sign(claims, key, { algorithm: 'HS512' }))).toBeNull();
		expect(auth.verifyToken('not a token')).toBeNull();
	});

	it('refuses sessions on a damaged store, and says so in the log once a minute', () => {
		const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
		const token = auth.generateToken(user('admin', 'hash-1'));
		writeStore([null]);
		const now = Date.now();
		const clock = vi.spyOn(Date, 'now').mockReturnValue(now);

		expect(auth.verifyToken(token)).toBeNull();
		expect(auth.verifyToken(token)).toBeNull();
		clock.mockReturnValue(now + 59_000);
		expect(auth.verifyToken(token)).toBeNull();
		expect(logged).toHaveBeenCalledTimes(1);
		expect(logged).toHaveBeenCalledWith('Sessions refused: the user store is unusable (malformed user record)');

		clock.mockReturnValue(now + 61_000);
		expect(auth.verifyToken(token)).toBeNull();
		expect(logged).toHaveBeenCalledTimes(2);
	});
});

describe('updatePassword', () => {
	it('saves a new user object 0600, keeps the others, and ends the old sessions', async () => {
		const original = user('admin', 'hash-1');
		const other = user('other', 'hash-9');
		writeStore([original, other]);
		const oldToken = auth.generateToken(original);
		const before = auth.getUser('admin')!;

		const { user: saved, durable } = await auth.updatePassword('admin', 'hash-1', 'NewPassw0rd');

		expect(durable).toBe(true);
		expect(await auth.verifyPassword('NewPassw0rd', saved.passwordHash)).toBe(true);
		expect(saved).toMatchObject({ username: 'admin', role: 'admin', createdAt: original.createdAt });
		expect(saved.updatedAt).not.toBe(original.updatedAt);
		expect(before.passwordHash).toBe('hash-1'); // the record read earlier wasn't mutated
		expect(storedUsers()).toEqual([saved, other]);
		expect(statSync(usersFile()).mode & 0o777).toBe(0o600);
		expect(auth.verifyToken(oldToken)).toBeNull();
		expect(auth.verifyToken(auth.generateToken(saved))).toEqual({ username: 'admin', role: 'admin' });
	});

	it('refuses with PasswordChangedElsewhere when the stored hash is not the one verified, and changes nothing', async () => {
		writeStore([user('admin', 'hash-2')]);
		const bytes = readFileSync(usersFile(), 'utf-8');

		await expect(auth.updatePassword('admin', 'hash-1', 'NewPassw0rd')).rejects.toBeInstanceOf(auth.PasswordChangedElsewhere);
		expect(readFileSync(usersFile(), 'utf-8')).toBe(bytes);
	});

	it('lets exactly one of two concurrent changes against the same hash win', async () => {
		writeStore([user('admin', 'hash-1')]);

		const results = await Promise.allSettled([
			auth.updatePassword('admin', 'hash-1', 'FirstPassw0rd'),
			auth.updatePassword('admin', 'hash-1', 'SecondPassw0rd'),
		]);

		const won = results.filter((r) => r.status === 'fulfilled') as PromiseFulfilledResult<{ user: User }>[];
		const lost = results.filter((r) => r.status === 'rejected') as PromiseRejectedResult[];
		expect(won).toHaveLength(1);
		expect(lost).toHaveLength(1);
		expect(lost[0].reason).toBeInstanceOf(auth.PasswordChangedElsewhere);
		expect(storedUsers()[0].passwordHash).toBe(won[0].value.user.passwordHash);
	});

	it('throws for an unknown user', async () => {
		writeStore([user('admin', 'hash-1')]);
		await expect(auth.updatePassword('ghost', 'hash-1', 'NewPassw0rd')).rejects.toThrow('not found');
	});
});
