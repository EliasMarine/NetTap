import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { SIGN_IN_FIRST } from '$lib/auth-errors';

/**
 * hooks.server.ts against the real auth module and real user-store files
 * (no mocks): first-run routes are open only for a readable, empty store.
 */

type Handle = typeof import('./hooks.server').handle;

let dataDir: string;
let handle: Handle;
let sessionToken: string;
let auth: typeof import('$lib/server/auth.js');

const resolve = vi.fn(async () => new Response('ok'));

function event(pathname: string, method = 'GET', cookie?: string, setupCookie?: string) {
	const url = new URL(`http://localhost${pathname}`);
	const jar: Record<string, string | undefined> = { nettap_token: cookie, nettap_setup: setupCookie };
	return {
		url,
		request: new Request(url, { method }),
		cookies: { get: (name: string) => jar[name] },
		locals: {} as App.Locals,
	} as unknown as Parameters<Handle>[0]['event'];
}

function run(pathname: string, method = 'GET', cookie?: string, setupCookie?: string) {
	return handle({ event: event(pathname, method, cookie, setupCookie), resolve });
}

/** NET-229 follow-up: during first run the wizard's API calls need the setup cookie. */
async function expectSetupCodeFirst(reply: Response | Promise<Response>): Promise<void> {
	const res = await reply;
	expect(res.status).toBe(401);
	expect(await res.json()).toEqual({ error: 'Enter the setup code first.' });
	expect(resolve).not.toHaveBeenCalled();
}

/** NET-197: an API call with no session gets 401 JSON, not a redirect, and the route never runs. */
async function expectUnauthorised(reply: Response | Promise<Response>): Promise<void> {
	const res = await reply;
	expect(res.status).toBe(401);
	expect(res.headers.get('content-type')).toBe('application/json');
	expect(await res.json()).toEqual({ error: SIGN_IN_FIRST });
	expect(resolve).not.toHaveBeenCalled();
}

function writeStore(contents: string): void {
	writeFileSync(join(dataDir, 'users.json'), contents, 'utf-8');
}

const ADMIN_STORE = JSON.stringify({
	users: [{ username: 'admin', passwordHash: 'x', role: 'admin', createdAt: '', updatedAt: '' }],
});

// OLD CODE START — NET-197: pages and API calls answer differently now, so the list is split
// const FIRST_RUN_PATHS = ['/setup', '/api/setup/configure', '/api/bridge/create', '/go-live'];
// OLD CODE END
// NET-277: /go-live no longer opens during first run; it stays for the after-setup and damaged-store checks
const FIRST_RUN_PAGES = ['/setup', '/go-live'];
// OLD CODE START — NET-280: /api/bridge/* is no longer a first-run path; it is checked as BRIDGE_API below
// const FIRST_RUN_APIS = ['/api/setup/configure', '/api/bridge/create'];
// OLD CODE END
// OLD CODE START — NET-290: the whole /api/setup prefix was open; only the wizard's exact calls are now
// const FIRST_RUN_APIS = ['/api/setup/configure'];
// OLD CODE END
/** The wizard's calls under /api/setup before the first admin exists: [method, path]. */
const FIRST_RUN_APIS: [string, string][] = [
	['GET', '/api/setup/nics'],
	['GET', '/api/setup/storage'],
	['POST', '/api/setup/storage'],
	['POST', '/api/setup/bridge'],
];
/** configure runs after the Account step, with the new admin's session: closed until the first admin exists. */
const CONFIGURE_API: [string, string] = ['POST', '/api/setup/configure'];
const BRIDGE_API = '/api/bridge/create';
// OLD CODE START — NET-290 review: only the OLD CODE blocks below still named it; pages and APIs are listed separately
// const FIRST_RUN_PATHS = [...FIRST_RUN_PAGES, ...FIRST_RUN_APIS.map(([, path]) => path)];
// OLD CODE END

beforeEach(async () => {
	dataDir = mkdtempSync(join(tmpdir(), 'nettap-hooks-'));
	vi.stubEnv('DATA_DIR', dataDir);
	vi.stubEnv('JWT_SECRET', 'hooks-store-test-secret');
	vi.resetModules();
	({ handle } = await import('./hooks.server'));
	auth = await import('$lib/server/auth.js');
	sessionToken = auth.generateToken({ username: 'admin', role: 'admin' });
	resolve.mockClear();
});

afterEach(() => {
	vi.unstubAllEnvs();
	rmSync(dataDir, { recursive: true, force: true });
});

describe('first-run routes with a real user store', () => {
	// OLD CODE START — NET-229 follow-up: the API paths need the setup cookie now; split below
	// it.each(FIRST_RUN_PATHS)('%s is open when the store does not exist', async (path) => {
	// 	await run(path, 'POST');
	// 	expect(resolve).toHaveBeenCalledTimes(1);
	// });
	//
	// it('an existing but empty store is still first run', async () => {
	// 	writeStore('{"users":[]}');
	// 	await run('/api/bridge/create', 'POST');
	// 	expect(resolve).toHaveBeenCalledTimes(1);
	// });
	// OLD CODE END
	// OLD CODE START — review: /go-live needs the setup cookie too
	// it.each(FIRST_RUN_PAGES)('page %s is open when the store does not exist', async (path) => {
	// 	await run(path, 'POST');
	// 	expect(resolve).toHaveBeenCalledTimes(1);
	// });
	// OLD CODE END
	it('/setup is open when the store does not exist', async () => {
		await run('/setup', 'POST');
		expect(resolve).toHaveBeenCalledTimes(1);
	});

	// NET-290 review: only /setup is a first-run page; a route under it needs the admin like any other page
	it('/setup/anything goes to /setup until the first admin exists, even with the code typed', async () => {
		await expect(run('/setup/anything')).rejects.toMatchObject({ status: 302, location: '/setup' });
		await expect(run('/setup/anything', 'GET', undefined, auth.setupToken() ?? '')).rejects.toMatchObject({
			status: 302,
			location: '/setup',
		});
		expect(resolve).not.toHaveBeenCalled();
	});

	// OLD CODE START — NET-277: with the code typed Go Live opened, but its capture-mode call got 401
	// it('/go-live goes to /setup until the code is typed', async () => {
	// 	await expect(run('/go-live')).rejects.toMatchObject({ status: 302, location: '/setup' });
	// 	expect(resolve).not.toHaveBeenCalled();
	//
	// 	await run('/go-live', 'GET', undefined, auth.setupToken() ?? '');
	// 	expect(resolve).toHaveBeenCalledTimes(1);
	// });
	// OLD CODE END
	it('/go-live goes to /setup until the first admin exists, even with the code typed', async () => {
		await expect(run('/go-live')).rejects.toMatchObject({ status: 302, location: '/setup' });
		await expect(run('/go-live', 'GET', undefined, auth.setupToken() ?? '')).rejects.toMatchObject({
			status: 302,
			location: '/setup',
		});
		writeStore('{"users":[]}');
		await expect(run('/go-live', 'GET', undefined, auth.setupToken() ?? '')).rejects.toMatchObject({
			status: 302,
			location: '/setup',
		});
		expect(resolve).not.toHaveBeenCalled();
	});

	// OLD CODE START — NET-290: FIRST_RUN_APIS holds [method, path] pairs now
	// it.each(FIRST_RUN_APIS)('API %s needs the setup cookie when the store does not exist', async (path) => {
	// 	await expectSetupCodeFirst(run(path, 'POST'));
	// 	await expectSetupCodeFirst(run(path, 'POST', undefined, 'not-the-token'));
	//
	// 	await run(path, 'POST', undefined, auth.setupToken() ?? '');
	// 	expect(resolve).toHaveBeenCalledTimes(1);
	// });
	// OLD CODE END
	it.each(FIRST_RUN_APIS)('API %s %s needs the setup cookie when the store does not exist', async (method, path) => {
		await expectSetupCodeFirst(run(path, method));
		await expectSetupCodeFirst(run(path, method, undefined, 'not-the-token'));

		await run(path, method, undefined, auth.setupToken() ?? '');
		expect(resolve).toHaveBeenCalledTimes(1);
	});

	// NET-290: the setup cookie opens the wizard's four calls and nothing else under /api/setup
	it.each([CONFIGURE_API, ['GET', '/api/setup/other'], ['POST', '/api/setup/nics'], ['GET', '/api/setup/bridge']])(
		'API %s %s needs a session before the first admin, even with the setup code typed',
		async (method, path) => {
			const code = auth.setupToken() ?? '';
			await expectUnauthorised(run(path, method, undefined, code));
			writeStore('{"users":[]}');
			await expectUnauthorised(run(path, method, undefined, code));
		}
	);

	it('a setup cookie stops working once the code is replaced', async () => {
		const stale = auth.setupToken() ?? '';
		rmSync(join(dataDir, 'setup-code'));
		// OLD CODE START — NET-280: the bridge is not a first-run API; /api/setup/configure stands in
		// await expectSetupCodeFirst(run('/api/bridge/create', 'POST', undefined, stale));
		// OLD CODE END
		// OLD CODE START — NET-290: configure is closed before the first admin; the wizard's GET nics stands in
		// await expectSetupCodeFirst(run('/api/setup/configure', 'POST', undefined, stale));
		// OLD CODE END
		await expectSetupCodeFirst(run('/api/setup/nics', 'GET', undefined, stale));
	});

	it('a setup cookie is not a session: after setup it opens nothing', async () => {
		const token = auth.setupToken() ?? '';
		writeStore(ADMIN_STORE);
		await expectUnauthorised(run('/api/bridge/create', 'POST', undefined, token));
		await expectUnauthorised(run('/api/bridge/create', 'POST', token));
	});

	// OLD CODE START — NET-280: the bridge is not a first-run API; /api/setup/configure stands in
	// it('an existing but empty store is still first run', async () => {
	// 	writeStore('{"users":[]}');
	// 	await run('/api/bridge/create', 'POST', undefined, auth.setupToken() ?? '');
	// 	expect(resolve).toHaveBeenCalledTimes(1);
	// });
	// OLD CODE END
	// OLD CODE START — NET-290: configure is closed before the first admin; the wizard's GET nics stands in
	// it('an existing but empty store is still first run', async () => {
	// 	writeStore('{"users":[]}');
	// 	await run('/api/setup/configure', 'POST', undefined, auth.setupToken() ?? '');
	// 	expect(resolve).toHaveBeenCalledTimes(1);
	// });
	// OLD CODE END
	it('an existing but empty store is still first run', async () => {
		writeStore('{"users":[]}');
		await run('/api/setup/nics', 'GET', undefined, auth.setupToken() ?? '');
		expect(resolve).toHaveBeenCalledTimes(1);
	});

	// NET-280: before the first admin exists the setup cookie opens the wizard's API, never the bridge
	it('the bridge needs a session before the first admin, even with the setup code typed', async () => {
		const code = auth.setupToken() ?? '';
		await expectUnauthorised(run(BRIDGE_API, 'POST', undefined, code));
		writeStore('{"users":[]}');
		await expectUnauthorised(run(BRIDGE_API, 'POST', undefined, code));
		await expectUnauthorised(run('/api/bridge/teardown', 'POST', undefined, code));
		await expectUnauthorised(run('/api/bridge/bypass/enable', 'POST', undefined, code));
	});

	// OLD CODE START — NET-197: API calls answer 401 JSON now; split into pages and API calls below
	// it.each(FIRST_RUN_PATHS)('%s needs a session once a user exists', async (path) => {
	// 	writeStore(ADMIN_STORE);
	// 	await expect(run(path, 'POST')).rejects.toMatchObject({ status: 302, location: '/login' });
	// 	expect(resolve).not.toHaveBeenCalled();
	//
	// 	await run(path, 'POST', sessionToken);
	// 	expect(resolve).toHaveBeenCalledTimes(1);
	// });
	//
	// it.each([
	// 	['corrupt JSON', '{"users": [ {'],
	// 	['wrong shape', '{"accounts": []}'],
	// 	['null', 'null'],
	// ])('a %s store fails closed', async (_label, contents) => {
	// 	writeStore(contents);
	// 	for (const path of FIRST_RUN_PATHS) {
	// 		await expect(run(path, 'POST')).rejects.toMatchObject({ location: '/login' });
	// 	}
	// 	expect(resolve).not.toHaveBeenCalled();
	// });
	//
	// it.skipIf(process.getuid?.() === 0)('an unreadable store fails closed', async () => {
	// 	writeStore(ADMIN_STORE);
	// 	chmodSync(join(dataDir, 'users.json'), 0o000);
	// 	await expect(run('/api/bridge/teardown', 'POST')).rejects.toMatchObject({ location: '/login' });
	// 	expect(resolve).not.toHaveBeenCalled();
	// });
	// OLD CODE END
	it.each(FIRST_RUN_PAGES)('page %s needs a session once a user exists', async (path) => {
		writeStore(ADMIN_STORE);
		await expect(run(path, 'POST')).rejects.toMatchObject({ status: 302, location: '/login' });
		expect(resolve).not.toHaveBeenCalled();

		await run(path, 'POST', sessionToken);
		expect(resolve).toHaveBeenCalledTimes(1);
	});

	// OLD CODE START — NET-290: FIRST_RUN_APIS holds [method, path] pairs now; configure joins them after setup
	// it.each(FIRST_RUN_APIS)('API %s needs a session once a user exists', async (path) => {
	// 	writeStore(ADMIN_STORE);
	// 	await expectUnauthorised(run(path, 'POST'));
	//
	// 	await run(path, 'POST', sessionToken);
	// 	expect(resolve).toHaveBeenCalledTimes(1);
	// });
	// OLD CODE END
	it.each([...FIRST_RUN_APIS, CONFIGURE_API])('API %s %s needs a session once a user exists', async (method, path) => {
		writeStore(ADMIN_STORE);
		await expectUnauthorised(run(path, method));
		await expectUnauthorised(run(path, method, undefined, auth.setupToken() ?? ''));

		await run(path, method, sessionToken);
		expect(resolve).toHaveBeenCalledTimes(1);
	});

	const DAMAGED: [string, string][] = [
		['corrupt JSON', '{"users": [ {'],
		['wrong shape', '{"accounts": []}'],
		['null', 'null'],
	];

	it.each(DAMAGED)('a %s store fails closed for pages: they go to /login, not setup', async (_label, contents) => {
		writeStore(contents);
		for (const path of FIRST_RUN_PAGES) {
			await expect(run(path, 'POST')).rejects.toMatchObject({ status: 302, location: '/login' });
		}
		expect(resolve).not.toHaveBeenCalled();
	});

	it.each(DAMAGED)('a %s store fails closed for first-run API calls: 401, never resolved', async (_label, contents) => {
		writeStore(contents);
		// OLD CODE START — NET-280: the bridge left FIRST_RUN_APIS but keeps this check
		// for (const path of FIRST_RUN_APIS) {
		// 	await expectUnauthorised(run(path, 'POST'));
		// }
		// OLD CODE END
		// OLD CODE START — NET-290: FIRST_RUN_APIS holds [method, path] pairs now
		// for (const path of [...FIRST_RUN_APIS, BRIDGE_API]) {
		// 	await expectUnauthorised(run(path, 'POST'));
		// }
		// OLD CODE END
		for (const [method, path] of [...FIRST_RUN_APIS, CONFIGURE_API, ['POST', BRIDGE_API]]) {
			await expectUnauthorised(run(path, method));
		}
	});

	it.skipIf(process.getuid?.() === 0)('an unreadable store fails closed for a page', async () => {
		writeStore(ADMIN_STORE);
		chmodSync(join(dataDir, 'users.json'), 0o000);
		await expect(run('/setup', 'POST')).rejects.toMatchObject({ status: 302, location: '/login' });
		expect(resolve).not.toHaveBeenCalled();
	});

	it.skipIf(process.getuid?.() === 0)('an unreadable store fails closed for an API call', async () => {
		writeStore(ADMIN_STORE);
		chmodSync(join(dataDir, 'users.json'), 0o000);
		await expectUnauthorised(run('/api/bridge/teardown', 'POST'));
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

	// OLD CODE START — NET-229 follow-up: they need the setup cookie too
	// it.each(BOOTSTRAP)('%s %s is open with no store', async (method, path) => {
	// 	await run(path, method);
	// 	expect(resolve).toHaveBeenCalledTimes(1);
	// });
	// OLD CODE END
	it.each(BOOTSTRAP)('%s %s is open with no store once the setup code is typed', async (method, path) => {
		await expectSetupCodeFirst(run(path, method));

		await run(path, method, undefined, auth.setupToken() ?? '');
		expect(resolve).toHaveBeenCalledTimes(1);
	});

	// OLD CODE START — NET-197: these API calls answer 401 JSON now, not a redirect to /login
	// it.each(BOOTSTRAP)('%s %s needs a session once a user exists', async (method, path) => {
	// 	writeStore(ADMIN_STORE);
	// 	await expect(run(path, method)).rejects.toMatchObject({ status: 302, location: '/login' });
	//
	// 	await run(path, method, sessionToken);
	// 	expect(resolve).toHaveBeenCalledTimes(1);
	// });
	//
	// it.each(BOOTSTRAP)('%s %s fails closed on a corrupt store', async (method, path) => {
	// 	writeStore('{"users": [ {');
	// 	await expect(run(path, method)).rejects.toMatchObject({ location: '/login' });
	// 	expect(resolve).not.toHaveBeenCalled();
	// });
	// OLD CODE END
	it.each(BOOTSTRAP)('%s %s needs a session once a user exists', async (method, path) => {
		writeStore(ADMIN_STORE);
		await expectUnauthorised(run(path, method));

		await run(path, method, sessionToken);
		expect(resolve).toHaveBeenCalledTimes(1);
	});

	it.each(BOOTSTRAP)('%s %s fails closed on a corrupt store', async (method, path) => {
		writeStore('{"users": [ {');
		await expectUnauthorised(run(path, method));
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
		// OLD CODE START — NET-197: an API call answers 401 JSON now, not a redirect to /setup
		// await expect(run(path, method)).rejects.toMatchObject({ status: 302, location: '/setup' });
		// expect(resolve).not.toHaveBeenCalled();
		// OLD CODE END
		await expectUnauthorised(run(path, method));
	});

	it('a page with no store still goes to setup', async () => {
		await expect(run('/alerts')).rejects.toMatchObject({ status: 302, location: '/setup' });
		expect(resolve).not.toHaveBeenCalled();
	});
});
