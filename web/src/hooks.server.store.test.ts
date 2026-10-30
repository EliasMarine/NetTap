import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

/**
 * hooks.server.ts against the real auth module and real user-store files
 * (no mocks): first-run routes are open only for a readable, empty store.
 */

type Handle = typeof import('./hooks.server').handle;

let dataDir: string;
let handle: Handle;
let sessionToken: string;

const resolve = vi.fn(async () => new Response('ok'));

function event(pathname: string, method = 'GET', cookie?: string) {
	const url = new URL(`http://localhost${pathname}`);
	return {
		url,
		request: new Request(url, { method }),
		cookies: { get: (name: string) => (name === 'nettap_token' ? cookie : undefined) },
		locals: {} as App.Locals,
	} as unknown as Parameters<Handle>[0]['event'];
}

function run(pathname: string, method = 'GET', cookie?: string) {
	return handle({ event: event(pathname, method, cookie), resolve });
}

function writeStore(contents: string): void {
	writeFileSync(join(dataDir, 'users.json'), contents, 'utf-8');
}

const ADMIN_STORE = JSON.stringify({
	users: [{ username: 'admin', passwordHash: 'x', role: 'admin', createdAt: '', updatedAt: '' }],
});

const FIRST_RUN_PATHS = ['/setup', '/api/setup/configure', '/api/bridge/create', '/go-live'];

beforeEach(async () => {
	dataDir = mkdtempSync(join(tmpdir(), 'nettap-hooks-'));
	vi.stubEnv('DATA_DIR', dataDir);
	vi.stubEnv('JWT_SECRET', 'hooks-store-test-secret');
	vi.resetModules();
	({ handle } = await import('./hooks.server'));
	const auth = await import('$lib/server/auth.js');
	sessionToken = auth.generateToken({ username: 'admin', role: 'admin' });
	resolve.mockClear();
});

afterEach(() => {
	vi.unstubAllEnvs();
	rmSync(dataDir, { recursive: true, force: true });
});

describe('first-run routes with a real user store', () => {
	it.each(FIRST_RUN_PATHS)('%s is open when the store does not exist', async (path) => {
		await run(path, 'POST');
		expect(resolve).toHaveBeenCalledTimes(1);
	});

	it('an existing but empty store is still first run', async () => {
		writeStore('{"users":[]}');
		await run('/api/bridge/create', 'POST');
		expect(resolve).toHaveBeenCalledTimes(1);
	});

	it.each(FIRST_RUN_PATHS)('%s needs a session once a user exists', async (path) => {
		writeStore(ADMIN_STORE);
		await expect(run(path, 'POST')).rejects.toMatchObject({ status: 302, location: '/login' });
		expect(resolve).not.toHaveBeenCalled();

		await run(path, 'POST', sessionToken);
		expect(resolve).toHaveBeenCalledTimes(1);
	});

	it.each([
		['corrupt JSON', '{"users": [ {'],
		['wrong shape', '{"accounts": []}'],
		['null', 'null'],
	])('a %s store fails closed', async (_label, contents) => {
		writeStore(contents);
		for (const path of FIRST_RUN_PATHS) {
			await expect(run(path, 'POST')).rejects.toMatchObject({ location: '/login' });
		}
		expect(resolve).not.toHaveBeenCalled();
	});

	it.skipIf(process.getuid?.() === 0)('an unreadable store fails closed', async () => {
		writeStore(ADMIN_STORE);
		chmodSync(join(dataDir, 'users.json'), 0o000);
		await expect(run('/api/bridge/teardown', 'POST')).rejects.toMatchObject({ location: '/login' });
		expect(resolve).not.toHaveBeenCalled();
	});

	it('a damaged store cannot be overwritten by createUser', async () => {
		writeStore('{"users": [ {');
		const auth = await import('$lib/server/auth.js');
		await expect(auth.createUser('attacker', 'Password1')).rejects.toThrow('User store unusable');
	});
});

describe('exact pre-Account wizard requests', () => {
	const BOOTSTRAP: [string, string][] = [
		['GET', '/api/settings/excluded-ips'],
		['POST', '/api/integrations/unifi/configure'],
		['POST', '/api/integrations/unifi/test'],
	];

	it.each(BOOTSTRAP)('%s %s is open with no store', async (method, path) => {
		await run(path, method);
		expect(resolve).toHaveBeenCalledTimes(1);
	});

	it.each(BOOTSTRAP)('%s %s needs a session once a user exists', async (method, path) => {
		writeStore(ADMIN_STORE);
		await expect(run(path, method)).rejects.toMatchObject({ status: 302, location: '/login' });

		await run(path, method, sessionToken);
		expect(resolve).toHaveBeenCalledTimes(1);
	});

	it.each(BOOTSTRAP)('%s %s fails closed on a corrupt store', async (method, path) => {
		writeStore('{"users": [ {');
		await expect(run(path, method)).rejects.toMatchObject({ location: '/login' });
		expect(resolve).not.toHaveBeenCalled();
	});

	it.each([
		['PUT', '/api/settings/excluded-ips'],
		['POST', '/api/settings/excluded-ips'],
		['GET', '/api/integrations/unifi/sites'],
		['GET', '/api/integrations/unifi/configure'],
		['POST', '/api/integrations/unifi/configure/x'],
		['POST', '/api/integrations/unifi/test/'],
		['GET', '/api/settings/excluded-ips/extra'],
	])('%s %s stays protected even with no store', async (method, path) => {
		await expect(run(path, method)).rejects.toMatchObject({ status: 302, location: '/setup' });
		expect(resolve).not.toHaveBeenCalled();
	});
});
