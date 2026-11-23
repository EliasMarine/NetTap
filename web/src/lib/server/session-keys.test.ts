import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import jwt from 'jsonwebtoken';

/**
 * NET-358 plan step 3a: the session keys, against real files in a temp DATA_DIR. Key writes go
 * through the real durable writer unless a test makes one fail (its own failure modes are in
 * durable-write.test.ts: a throw before the rename, `durable: false` after it).
 */

const writes = vi.hoisted(() => ({
	override: null as null | ((file: string, contents: string) => { durable: boolean } | undefined),
}));

vi.mock('./durable-write.js', async (importOriginal) => {
	const real = await importOriginal<typeof import('./durable-write.js')>();
	return {
		writeFileDurably: vi.fn(
			(file: string, contents: string) => writes.override?.(file, contents) ?? real.writeFileDurably(file, contents)
		),
	};
});

type Keys = typeof import('./session-keys.js');
type Auth = typeof import('./auth.js');

let dataDir: string;
let keys: Keys;
let auth: Auth;

const ADMIN = { username: 'admin', passwordHash: '$argon2id$stored', role: 'admin', createdAt: '', updatedAt: '' };
const legacyFile = () => join(dataDir, 'jwt-secret.txt');
const v2File = () => join(dataDir, 'jwt-secret-v2.txt');
const KEY = /^[0-9a-f]{128}$/;

/** An older build's key, read its exact way (auth.ts before NET-358): readFileSync(…, 'utf-8').trim(). */
const oldKey = () => readFileSync(legacyFile(), 'utf-8').trim();

/** An older build's session check: jwt.verify with its key and nothing else. */
function oldVerifierAccepts(token: string, key: string = oldKey()): boolean {
	try {
		jwt.verify(token, key);
		return true;
	} catch {
		return false;
	}
}

/** A sign-in on an older build: { username, role } signed with its key. */
const oldBuildLogin = (key: string = oldKey()) => jwt.sign({ username: 'admin', role: 'admin' }, key, { expiresIn: '24h' });

/** A fresh process, as after a restart or an upgrade. */
async function load(): Promise<void> {
	vi.resetModules();
	keys = await import('./session-keys.js');
	auth = await import('./auth.js');
}

async function start(): Promise<void> {
	await load();
	keys.initSessionKeys();
}

async function writer() {
	return vi.mocked((await import('./durable-write.js')).writeFileDurably);
}

beforeEach(async () => {
	dataDir = mkdtempSync(join(tmpdir(), 'nettap-keys-'));
	vi.stubEnv('DATA_DIR', dataDir);
	vi.stubEnv('JWT_SECRET', '');
	writeFileSync(join(dataDir, 'users.json'), JSON.stringify({ users: [ADMIN] }));
	writes.override = null;
	await load();
});

afterEach(() => {
	vi.unstubAllEnvs();
	vi.restoreAllMocks();
	rmSync(dataDir, { recursive: true, force: true });
});

describe('initSessionKeys', () => {
	it('works in a fresh folder without privileges: both keys are 128 hex, no newline, 0600', async () => {
		const parent = dataDir;
		dataDir = join(parent, 'not-yet');
		vi.stubEnv('DATA_DIR', dataDir);
		await start();

		for (const file of [legacyFile(), v2File()]) {
			expect(readFileSync(file, 'utf-8')).toMatch(KEY);
			expect(statSync(file).mode & 0o777).toBe(0o600);
		}
		expect(readFileSync(legacyFile(), 'utf-8')).not.toBe(readFileSync(v2File(), 'utf-8'));
		dataDir = parent;
	});

	it('replaces the legacy key at every start, and makes the v2 key once and keeps it', async () => {
		await start();
		const v2 = readFileSync(v2File(), 'utf-8');
		const legacy = [oldKey()];
		for (let i = 0; i < 2; i++) {
			await start();
			legacy.push(oldKey());
		}

		expect(new Set(legacy).size).toBe(3);
		expect(readFileSync(v2File(), 'utf-8')).toBe(v2);
	});

	it('returns the v2 key, the one getJwtSecret then gives', async () => {
		await load();
		const key = keys.initSessionKeys();
		expect(key).toBe(readFileSync(v2File(), 'utf-8'));
		expect(keys.getJwtSecret()).toBe(key);
	});

	it.each([
		['with no newline, as the old writer left it', ''],
		['with a newline', '\n'],
	])('replaces a legacy key %s by one that differs after trimming', async (_, end) => {
		const before = 'c'.repeat(128);
		writeFileSync(legacyFile(), `${before}${end}`);
		await start();
		expect(oldKey()).not.toBe(before);
		expect(readFileSync(legacyFile(), 'utf-8')).toMatch(KEY);
	});

	it('ignores JWT_SECRET, saying so once', async () => {
		const warned = vi.spyOn(console, 'warn').mockImplementation(() => {});
		vi.stubEnv('JWT_SECRET', 'an old fixed key');
		await start();

		expect(warned).toHaveBeenCalledTimes(1);
		// OLD CODE: expect(warned).toHaveBeenCalledWith(keys.JWT_SECRET_WARNING); (NET-358 review: the sentence itself is checked)
		expect(warned).toHaveBeenCalledWith("JWT_SECRET is set, but this NetTap no longer reads it. Remove it from the web container's settings.");
		expect(keys.legacySecretInEnv()).toBe(true);
		expect(existsSync(v2File())).toBe(true);
		const oldBuildToken = jwt.sign({ username: 'admin', role: 'admin', pwd: auth.passwordStamp(ADMIN.passwordHash) }, 'an old fixed key');
		expect(auth.verifyToken(oldBuildToken)).toBeNull();
	});

	it.each([
		['empty', ''],
		['truncated', 'ab'.repeat(32)],
		['malformed', 'z'.repeat(128)],
		['upper-case', 'A'.repeat(128)],
	])('refuses to start on a %s v2 key file, leaves it, and caches nothing', async (_, contents) => {
		writeFileSync(v2File(), contents);
		await load();

		expect(() => keys.initSessionKeys()).toThrow(`${v2File()} doesn't hold a valid session key.`);
		expect(() => auth.generateToken(ADMIN)).toThrow(/doesn't hold a valid session key/);
		expect(readFileSync(v2File(), 'utf-8')).toBe(contents);
	});

	it('refuses to start on an unreadable v2 key file', async () => {
		mkdirSync(v2File()); // reading a folder fails whoever runs the test, root included
		await load();
		expect(() => keys.initSessionKeys()).toThrow(`${v2File()} can't be read (EISDIR).`);
	});

	it('accepts the v2 key with a trailing newline, read trimmed', async () => {
		writeFileSync(v2File(), `${'d'.repeat(128)}\n`);
		await start();
		expect(() => jwt.verify(auth.generateToken(ADMIN), 'd'.repeat(128))).not.toThrow();
	});

	const rename = (file: string) => {
		throw Object.assign(new Error(`injected rename failure for ${file}`), { code: 'EIO' });
	};
	const renameError = (file: string) => `injected rename failure for ${file}`;
	const notConfirmed = (file: string) => `Couldn't confirm ${file} reached the disk, so the web app won't start.`;
	it.each([
		['the legacy key write fails before its rename', 'jwt-secret.txt', rename, renameError],
		['the v2 key write fails before its rename', 'jwt-secret-v2.txt', rename, renameError],
		['the legacy key lands but its folder fsync fails', 'jwt-secret.txt', () => ({ durable: false }), notConfirmed],
		['the v2 key lands but its folder fsync fails', 'jwt-secret-v2.txt', () => ({ durable: false }), notConfirmed],
	])('throws, and caches no key, when %s', async (_, name, fault, message) => {
		vi.spyOn(console, 'error').mockImplementation(() => {});
		writes.override = (file) => (file === join(dataDir, name) ? fault(file) : undefined);
		await load();

		// OLD CODE: expect(() => keys.initSessionKeys()).toThrow(); (NET-358 review: any throw passed, including the wrong one)
		expect(() => keys.initSessionKeys()).toThrow(message(join(dataDir, name)));

		// nothing was cached: asking for the key runs the start-up steps again
		writes.override = null;
		const write = await writer();
		const before = write.mock.calls.length;
		expect(keys.getJwtSecret()).toMatch(KEY);
		expect(write.mock.calls.length).toBeGreaterThan(before);
	});
});

describe('an older build after a downgrade (a stand-in for its session check)', () => {
	it('trusts a pre-migration cookie before the migration and nothing from before it after', async () => {
		const before = 'e'.repeat(128);
		writeFileSync(legacyFile(), before); // as the old writer left it: no newline
		const preMigration = oldBuildLogin();
		expect(oldVerifierAccepts(preMigration)).toBe(true);

		await start();

		expect(oldKey()).not.toBe(before);
		expect(oldVerifierAccepts(preMigration)).toBe(false);
		expect(oldVerifierAccepts(auth.generateToken(ADMIN))).toBe(false);
		// positive control: a token signed with the new legacy key, read the stand-in's way, passes
		expect(oldVerifierAccepts(oldBuildLogin())).toBe(true);
	});

	it('two downgrades: a session issued during the first rollback is refused after the next start', async () => {
		await start();
		const v2Session = auth.generateToken(ADMIN);

		// first downgrade: the older build signs someone in with the legacy key it reads
		const rollbackEra = oldBuildLogin();
		expect(oldVerifierAccepts(rollbackEra)).toBe(true);

		// upgrade again: the v2 key is kept, so its sessions verify while the password is unchanged
		await start();
		expect(auth.verifyToken(v2Session)).toEqual({ username: 'admin', role: 'admin' });

		// second downgrade: the rollback-era session is not trusted any more
		expect(oldVerifierAccepts(rollbackEra)).toBe(false);
	});

	it("never signs with a JWT_SECRET in the environment: a token signed with it fails verifyToken", async () => {
		vi.spyOn(console, 'warn').mockImplementation(() => {});
		const secret = 'the value an older build signs with';
		vi.stubEnv('JWT_SECRET', secret);
		await start();

		const signedWithIt = jwt.sign({ username: 'admin', role: 'admin', pwd: auth.passwordStamp(ADMIN.passwordHash) }, secret, { expiresIn: '24h' });
		expect(auth.verifyToken(signedWithIt)).toBeNull();
		const issued = auth.generateToken(ADMIN);
		expect(oldVerifierAccepts(issued, secret)).toBe(false); // an older build reads JWT_SECRET's raw bytes
		expect(auth.verifyToken(issued)).toEqual({ username: 'admin', role: 'admin' });
	});
});
