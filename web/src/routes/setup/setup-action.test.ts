import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs';
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

function adminEvent(username: string) {
	const body = new FormData();
	body.set('username', username);
	body.set('password', 'Passw0rdOK');
	body.set('confirmPassword', 'Passw0rdOK');
	const cookies = { set: vi.fn(), get: vi.fn(), delete: vi.fn() };
	const request = new Request('http://localhost/setup?/createAdmin', { method: 'POST', body });
	const event = { request, cookies } as unknown as Parameters<CreateAdmin>[0];
	return { event, cookies };
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
	} = (await import('./+page.server')) as { actions: { createAdmin: CreateAdmin } });
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
