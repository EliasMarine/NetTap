import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { SIGN_IN_FIRST } from '$lib/auth-errors';

/**
 * POST /api/account/password (NET-358) with the real auth, login throttle and user store in a temp
 * DATA_DIR. The store's writes go through the real durable writer unless a test makes the folder
 * fsync fail (durable-write.test.ts covers how that maps to `durable: false`).
 */

const writes = vi.hoisted(() => ({ notDurable: false }));

vi.mock('$lib/server/durable-write.js', async (importOriginal) => {
	const real = await importOriginal<typeof import('$lib/server/durable-write.js')>();
	return {
		writeFileDurably: vi.fn((file: string, contents: string) => {
			const result = real.writeFileDurably(file, contents);
			return writes.notDurable && file.endsWith('users.json') ? { durable: false } : result;
		}),
	};
});

type Post = typeof import('./+server').POST;
type Auth = typeof import('$lib/server/auth.js');

const OLD = 'OldPassw0rd';
const NEW = 'NewPassw0rd';
const ALICE = { username: 'alice', role: 'admin' };
const NOT_DURABLE =
	"Your new password is active. NetTap couldn't confirm it reached the disk: if the box loses power soon, the old password may work again.";

let dataDir: string;
let POST: Post;
let auth: Auth;

const usersFile = () => join(dataDir, 'users.json');

async function call(body: unknown, { signedIn = true, ip = '192.0.2.10' } = {}) {
	const request = new Request('http://localhost/api/account/password', {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: typeof body === 'string' ? body : JSON.stringify(body),
	});
	const cookies = { set: vi.fn(), get: vi.fn(), delete: vi.fn() };
	const event = { request, locals: { user: signedIn ? ALICE : undefined }, cookies, getClientAddress: () => ip };
	const res = await POST(event as unknown as Parameters<Post>[0]);
	const cookie = cookies.set.mock.calls.find(([name]) => name === 'nettap_token')?.[1] as string | undefined;
	return { status: res.status, headers: res.headers, body: await res.json(), cookie };
}

beforeEach(async () => {
	dataDir = mkdtempSync(join(tmpdir(), 'nettap-password-'));
	vi.stubEnv('DATA_DIR', dataDir);
	vi.stubEnv('JWT_SECRET', '');
	writes.notDurable = false;
	vi.resetModules(); // fresh login throttles per test
	auth = await import('$lib/server/auth.js');
	({ POST } = await import('./+server'));
	const now = new Date().toISOString();
	const passwordHash = await auth.hashPassword(OLD);
	writeFileSync(usersFile(), JSON.stringify({ users: [{ ...ALICE, passwordHash, createdAt: now, updatedAt: now }] }));
});

afterEach(() => {
	vi.unstubAllEnvs();
	vi.restoreAllMocks();
	rmSync(dataDir, { recursive: true, force: true });
});

describe('POST /api/account/password', () => {
	it('changes the password, signs this browser in again and ends the other sessions', async () => {
		const info = vi.spyOn(console, 'info').mockImplementation(() => {});
		const oldSession = auth.generateToken(auth.getUser('alice')!);

		const { status, body, cookie } = await call({ current: OLD, password: NEW });

		expect(status).toBe(200);
		expect(body).toEqual({ success: true });
		expect(auth.verifyToken(cookie!)).toEqual(ALICE);
		expect(auth.verifyToken(oldSession)).toBeNull();
		expect(await auth.verifyPassword(NEW, auth.getUser('alice')!.passwordHash)).toBe(true);
		expect(info).toHaveBeenCalledTimes(1);
		expect(info).toHaveBeenCalledWith('Password changed for alice.');
	});

	it('answers 200 with a warning and a working cookie when the new store may not have reached the disk', async () => {
		writes.notDurable = true;

		const { status, body, cookie } = await call({ current: OLD, password: NEW });

		expect(status).toBe(200);
		expect(body).toEqual({ success: true, warning: NOT_DURABLE });
		expect(auth.verifyToken(cookie!)).toEqual(ALICE);
	});

	it('answers 401 without a session', async () => {
		const { status, body } = await call({ current: OLD, password: NEW }, { signedIn: false });
		expect(status).toBe(401);
		expect(body).toEqual({ error: SIGN_IN_FIRST });
	});

	it('refuses with 409 while JWT_SECRET is set, and changes nothing', async () => {
		vi.stubEnv('JWT_SECRET', 'an old fixed key');
		const bytes = readFileSync(usersFile(), 'utf-8');

		const { status, body, cookie } = await call({ current: OLD, password: NEW });

		expect(status).toBe(409);
		expect(body).toEqual({
			error: "Remove JWT_SECRET from the web container's settings first: an older NetTap would still trust sessions signed with it.",
		});
		expect(cookie).toBeUndefined();
		expect(readFileSync(usersFile(), 'utf-8')).toBe(bytes);
	});

	it.each([
		['bad JSON', '{'],
		['no body fields', {}],
		['null', 'null'],
		['a number for a field', { current: 1, password: NEW }],
		['an empty current password', { current: '', password: NEW }],
		['an empty new password', { current: OLD, password: '' }],
	])('answers 400 for %s', async (_, body) => {
		const res = await call(body);
		expect(res.status).toBe(400);
		expect(res.body).toEqual({ error: 'Enter your current password and a new one.' });
	});

	it.each([
		['Sh0rt', 'Password must be at least 8 characters.'],
		['nouppercase1', 'Password must contain at least one uppercase letter.'],
		[`Aa1${'x'.repeat(1022)}`, 'Password must be at most 1,024 characters.'],
	])('answers 400 with the rule a weak password breaks (%#)', async (password, error) => {
		const res = await call({ current: OLD, password });
		expect(res.status).toBe(400);
		expect(res.body).toEqual({ error });
	});

	it('answers 400 when the new password is the current one', async () => {
		const res = await call({ current: OLD, password: OLD });
		expect(res.status).toBe(400);
		expect(res.body).toEqual({ error: "Choose a new password that's different from the current one." });
	});

	it('answers 401 for a wrong current password, and changes nothing', async () => {
		const bytes = readFileSync(usersFile(), 'utf-8');

		const res = await call({ current: 'Wr0ngPassword', password: NEW });

		expect(res.status).toBe(401);
		expect(res.body).toEqual({ error: "Your current password isn't right." });
		expect(res.cookie).toBeUndefined();
		expect(readFileSync(usersFile(), 'utf-8')).toBe(bytes);
	});

	it("answers 429 with Retry-After once the login's own limit is reached", async () => {
		for (let i = 0; i < 5; i++) {
			expect((await call({ current: 'Wr0ngPassword', password: NEW })).status).toBe(401);
		}

		const res = await call({ current: OLD, password: NEW });

		expect(res.status).toBe(429);
		expect(res.headers.get('Retry-After')).toBe('60');
		expect(res.body).toEqual({ error: 'Too many login attempts. Please wait 60 seconds and try again.' });
	});

	it('answers 429 with no Retry-After when the throttle gives no wait', async () => {
		// LoginResult allows a 429 without retryAfter; the real throttle always gives one, so stand in for it
		vi.resetModules();
		vi.doMock('$lib/server/login.js', () => ({
			attemptLogin: async () => ({ ok: false, status: 429, error: 'Too many login attempts.' }),
		}));
		({ POST } = await import('./+server'));
		vi.doUnmock('$lib/server/login.js');

		const res = await call({ current: OLD, password: NEW });

		expect(res.status).toBe(429);
		expect(res.headers.has('Retry-After')).toBe(false);
		expect(res.body).toEqual({ error: 'Too many login attempts.' });
	});

	it('answers 400 for a current password over 1,024 characters before it is checked, spending no login attempt', async () => {
		const res = await call({ current: `Aa1${'x'.repeat(1022)}`, password: NEW });

		expect(res.status).toBe(400);
		expect(res.body).toEqual({ error: 'Enter your current password and a new one.' });
		// all five of the address's attempts a minute are left: exactly 1,024 characters is still checked, then four more
		const statuses = [(await call({ current: `Aa1${'x'.repeat(1021)}`, password: NEW })).status];
		for (let i = 0; i < 4; i++) statuses.push((await call({ current: 'Wr0ngPassword', password: NEW })).status);
		expect(statuses).toEqual([401, 401, 401, 401, 401]);
	});

	it('answers 500 without the error text when the store cannot be saved, and the old password still works', async () => {
		const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
		mkdirSync(join(dataDir, 'users.json.tmp', 'blocker'), { recursive: true }); // the writer can't clear its temp path

		const res = await call({ current: OLD, password: NEW });

		expect(res.status).toBe(500);
		expect(res.body).toEqual({ error: "Couldn't save the new password. The web container's log has the details." });
		expect(res.cookie).toBeUndefined();
		expect(logged).toHaveBeenCalledWith('Changing the password for alice failed:', expect.any(Error));
		expect(await auth.verifyPassword(OLD, auth.getUser('alice')!.passwordHash)).toBe(true);
	});

	it('lets exactly one of two changes that verified the same password win; the other gets 409 and no cookie', async () => {
		vi.spyOn(console, 'info').mockImplementation(() => {});

		const results = await Promise.all([
			call({ current: OLD, password: 'FirstPassw0rd' }),
			call({ current: OLD, password: 'SecondPassw0rd' }),
		]);

		expect(results.map((r) => r.status).sort()).toEqual([200, 409]);
		const winner = results.find((r) => r.status === 200)!;
		const loser = results.find((r) => r.status === 409)!;
		expect(loser.body).toEqual({
			error: 'Your password was just changed in another window. Sign in again with the new password.',
		});
		expect(loser.cookie).toBeUndefined();
		expect(auth.verifyToken(winner.cookie!)).toEqual(ALICE);
	});
});
