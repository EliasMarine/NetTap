import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

/**
 * The real createAdmin action and createFirstAdmin against a real temp user
 * store: concurrent first-admin requests create exactly one admin, and only
 * the winner is signed in.
 */

type Auth = typeof import('$lib/server/auth.js');
type CreateAdmin = (typeof import('./+page.server'))['actions']['createAdmin'];

let dataDir: string;
let auth: Auth;
let createAdmin: CreateAdmin;

// NET-229: the action needs the setup code; by default each event sends the one on disk
function adminEvent(username: string, setupCode: string | null = currentCode(), ip = '192.0.2.10') {
	const body = new FormData();
	if (setupCode !== null) body.set('setupCode', setupCode);
	body.set('username', username);
	body.set('password', 'Passw0rdOK');
	body.set('confirmPassword', 'Passw0rdOK');
	const cookies = { set: vi.fn(), get: vi.fn(), delete: vi.fn() };
	const request = new Request('http://localhost/setup?/createAdmin', { method: 'POST', body });
	const event = { request, cookies, getClientAddress: () => ip } as unknown as Parameters<CreateAdmin>[0];
	return { event, cookies };
}

const codeFile = () => join(dataDir, 'setup-code');

/** The code nettap-web made (as its init hook does at start). */
function currentCode(): string {
	return auth.ensureSetupCode() ?? '';
}

function storedUsers(): { username: string }[] {
	return JSON.parse(readFileSync(join(dataDir, 'users.json'), 'utf-8')).users;
}

beforeEach(async () => {
	dataDir = mkdtempSync(join(tmpdir(), 'nettap-setup-'));
	vi.stubEnv('DATA_DIR', dataDir);
	vi.stubEnv('JWT_SECRET', 'setup-action-test-secret');
	vi.resetModules();
	auth = await import('$lib/server/auth.js');
	({
		actions: { createAdmin },
	} = (await import('./+page.server')) as unknown as { actions: { createAdmin: CreateAdmin } });
});

afterEach(() => {
	vi.unstubAllEnvs();
	rmSync(dataDir, { recursive: true, force: true });
});

describe('createFirstAdmin', () => {
	it('lets exactly one of two concurrent calls create the admin', async () => {
		const results = await Promise.allSettled([
			auth.createFirstAdmin('alice', 'Passw0rdOK'),
			auth.createFirstAdmin('mallory', 'Passw0rdOK'),
		]);

		expect(results.map((r) => r.status).sort()).toEqual(['fulfilled', 'rejected']);
		const loser = results.find((r) => r.status === 'rejected') as PromiseRejectedResult;
		expect(loser.reason).toBeInstanceOf(auth.SetupAlreadyComplete);
		expect(storedUsers()).toHaveLength(1);
	});

	it('refuses once any user exists', async () => {
		writeFileSync(join(dataDir, 'users.json'), JSON.stringify({ users: [{ username: 'root' }] }));
		await expect(auth.createFirstAdmin('alice', 'Passw0rdOK')).rejects.toBeInstanceOf(
			auth.SetupAlreadyComplete
		);
		expect(storedUsers()).toEqual([{ username: 'root' }]);
	});

	it('keeps serving after a failed attempt', async () => {
		writeFileSync(join(dataDir, 'users.json'), 'not json');
		await expect(auth.createFirstAdmin('alice', 'Passw0rdOK')).rejects.toThrow('User store unusable');

		rmSync(join(dataDir, 'users.json'));
		await expect(auth.createFirstAdmin('alice', 'Passw0rdOK')).resolves.toMatchObject({
			username: 'alice',
			role: 'admin',
		});
	});
});

describe('createAdmin action', () => {
	it('signs in the new admin with a valid session cookie', async () => {
		const { event, cookies } = adminEvent('alice');

		const result = await createAdmin(event);

		expect(result).toEqual({ success: true, username: 'alice' });
		expect(cookies.set).toHaveBeenCalledTimes(1);
		const [name, token, opts] = cookies.set.mock.calls[0];
		expect(name).toBe('nettap_token');
		expect(auth.verifyToken(token)).toEqual({ username: 'alice', role: 'admin' });
		expect(opts).toMatchObject({ httpOnly: true, path: '/' });
	});

	it('gives a cookie only to the winner of a concurrent setup race', async () => {
		const a = adminEvent('alice');
		const b = adminEvent('mallory');

		const results = await Promise.allSettled([createAdmin(a.event), createAdmin(b.event)]);

		const winners = results.filter((r) => r.status === 'fulfilled');
		const losers = results.filter((r) => r.status === 'rejected') as PromiseRejectedResult[];
		expect(winners).toHaveLength(1);
		expect(losers).toHaveLength(1);
		expect(losers[0].reason).toMatchObject({ status: 302, location: '/login' });
		expect(a.cookies.set.mock.calls.length + b.cookies.set.mock.calls.length).toBe(1);
		expect(storedUsers()).toHaveLength(1);
	});

	it('redirects to /login without a cookie once an admin exists', async () => {
		await auth.createFirstAdmin('alice', 'Passw0rdOK');
		const { event, cookies } = adminEvent('mallory');

		await expect(createAdmin(event)).rejects.toMatchObject({ status: 302, location: '/login' });
		expect(cookies.set).not.toHaveBeenCalled();
	});
});

describe('setup code (A13, NET-229)', () => {
	it('refuses to create the admin without the setup code', async () => {
		const { event, cookies } = adminEvent('mallory', null);

		const result = await createAdmin(event);

		expect(result).toMatchObject({ status: 400, data: { error: expect.stringContaining('setup code') } });
		expect(auth.hasUsers()).toBe(false);
		expect(cookies.set).not.toHaveBeenCalled();
	});

	it('refuses a wrong code', async () => {
		currentCode();
		const { event } = adminEvent('mallory', 'ABCD-EFGH-JKMN');

		expect(await createAdmin(event)).toMatchObject({ status: 400 });
		expect(auth.hasUsers()).toBe(false);
	});

	it('takes the code in any case and spacing, and it works once', async () => {
		const code = currentCode();
		expect(code).toMatch(/^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$/);
		expect(statSync(codeFile()).mode & 0o777).toBe(0o600);

		const { event } = adminEvent('alice', ` ${code.toLowerCase().replaceAll('-', ' ')} `);
		expect(await createAdmin(event)).toEqual({ success: true, username: 'alice' });

		expect(existsSync(codeFile())).toBe(false);
		// the same code again: setup is done, so it goes to /login
		await expect(createAdmin(adminEvent('mallory', code).event)).rejects.toMatchObject({
			status: 302,
			location: '/login',
		});
		expect(storedUsers().map((u) => u.username)).toEqual(['alice']);
	});

	it('limits tries per address: the 6th in a minute is refused even with the right code', async () => {
		const code = currentCode();
		for (let i = 0; i < 5; i++) {
			expect(await createAdmin(adminEvent('mallory', 'ABCD-EFGH-JKMN').event)).toMatchObject({ status: 400 });
		}

		expect(await createAdmin(adminEvent('alice', code).event)).toMatchObject({
			status: 429,
			data: { error: expect.stringContaining('Too many attempts') },
		});
		expect(auth.hasUsers()).toBe(false);
		// another address still has its own budget
		expect(await createAdmin(adminEvent('alice', code, '192.0.2.11').event)).toEqual({
			success: true,
			username: 'alice',
		});
	});

	it.each([
		['empty', ''],
		['truncated', 'ABCD-EF'],
		['malformed', 'not a code at all!'],
	])('never matches an %s code file, and replaces it with a whole code', async (_kind, contents) => {
		writeFileSync(codeFile(), contents);
		const short = contents.replace(/[^A-Za-z0-9]/g, '');

		expect(await createAdmin(adminEvent('mallory', short).event)).toMatchObject({ status: 400 });
		expect(auth.hasUsers()).toBe(false);
		// the next wizard load (or start) writes a whole code in its place
		const fresh = auth.ensureSetupCode();
		expect(fresh).toMatch(/^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$/);
		expect(readFileSync(codeFile(), 'utf-8').trim()).toBe(fresh);
	});

	it('an install that already has an admin gets no code and signs in as before', async () => {
		await auth.createFirstAdmin('owner', 'Passw0rdOK');
		writeFileSync(codeFile(), 'ABCD-EFGH-JKMN\n'); // left over from an older start

		expect(auth.ensureSetupCode()).toBeNull();
		expect(existsSync(codeFile())).toBe(false);
		const { attemptLogin } = await import('$lib/server/login.js');
		await expect(attemptLogin('192.0.2.10', 'owner', 'Passw0rdOK')).resolves.toMatchObject({ ok: true });
		// no code is asked for: the action still just sends a second admin to /login
		await expect(createAdmin(adminEvent('mallory', null).event)).rejects.toMatchObject({
			status: 302,
			location: '/login',
		});
	});
});
