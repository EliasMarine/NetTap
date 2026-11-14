import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { redirect } from '@sveltejs/kit';
import { SIGN_IN_FIRST } from '$lib/auth-errors';

// Mock $lib/server/auth.js
const mockVerifyToken = vi.fn();
const mockHasUsers = vi.fn();
const mockSetupTokenValid = vi.fn();

vi.mock('$lib/server/auth.js', () => ({
	verifyToken: mockVerifyToken,
	hasUsers: mockHasUsers,
	setupTokenValid: mockSetupTokenValid,
}));

// Mock @sveltejs/kit redirect to throw like the real one
vi.mock('@sveltejs/kit', async (importOriginal) => {
	const actual = await importOriginal<typeof import('@sveltejs/kit')>();
	return {
		...actual,
		redirect: vi.fn().mockImplementation((status: number, location: string) => {
			const error = new Error('redirect');
			(error as any).status = status;
			(error as any).location = location;
			throw error;
		}),
	};
});

function createMockEvent(pathname: string, token?: string, user?: any, method = 'GET', headers: Record<string, string> = {}) {
	const url = new URL(`http://localhost${pathname}`);
	return {
		url,
		request: new Request(url, { method, headers }),
		cookies: {
			get: vi.fn().mockImplementation((name: string) => {
				if (name === 'nettap_token') return token;
				return undefined;
			}),
			set: vi.fn(),
			delete: vi.fn(),
			serialize: vi.fn(),
			getAll: vi.fn().mockReturnValue([]),
		},
		locals: { user } as any,
	};
}

let handle: any;

describe('hooks.server', () => {
	const mockResolve = vi.fn().mockImplementation(async (event: any) => new Response('ok'));

	/** NET-197: a 401 with the JSON body, not a redirect, and the route never runs. */
	async function expectUnauthorised(reply: Promise<Response>): Promise<void> {
		const res = await reply;
		expect(res.status).toBe(401);
		expect(res.headers.get('content-type')).toBe('application/json');
		expect(await res.json()).toEqual({ error: SIGN_IN_FIRST });
		expect(mockResolve).not.toHaveBeenCalled();
	}

	beforeEach(async () => {
		vi.resetModules();
		mockVerifyToken.mockReset();
		mockHasUsers.mockReset();
		mockSetupTokenValid.mockReset();
		mockResolve.mockClear();

		// Re-mock after resetModules
		vi.mock('$lib/server/auth.js', () => ({
			verifyToken: mockVerifyToken,
			hasUsers: mockHasUsers,
			setupTokenValid: mockSetupTokenValid,
		}));
		vi.mock('@sveltejs/kit', async (importOriginal) => {
			const actual = await importOriginal<typeof import('@sveltejs/kit')>();
			return {
				...actual,
				redirect: vi.fn().mockImplementation((status: number, location: string) => {
					const error = new Error('redirect');
					(error as any).status = status;
					(error as any).location = location;
					throw error;
				}),
			};
		});

		const mod = await import('./hooks.server');
		handle = mod.handle;
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	describe('public paths', () => {
		it('allows /login without auth', async () => {
			mockHasUsers.mockReturnValue(true);
			const event = createMockEvent('/login');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		// OLD CODE START — NET-193: the tools and lookups need a login now
		// it('allows /tools without auth', async () => {
		// 	mockHasUsers.mockReturnValue(true);
		// 	const event = createMockEvent('/tools/subnet-calc');
		//
		// 	await handle({ event, resolve: mockResolve });
		// 	expect(mockResolve).toHaveBeenCalledWith(event);
		// });
		// OLD CODE END

		// OLD CODE START — NET-197: the API paths answer 401 JSON now; split into pages and API calls below
		// it.each([
		// 	'/tools',
		// 	'/tools/subnet-calc',
		// 	'/tools/ping',
		// 	'/lookup/dns',
		// 	'/lookup/whois',
		// 	'/api/tools',
		// 	'/api/tools/ping',
		// 	'/api/tools/mac-lookup/aa:bb:cc:dd:ee:ff',
		// 	'/api/lookup/dns/1.1.1.1',
		// 	'/api/lookup/whois/1.1.1.1',
		// ])('sends %s to /login without a session (NET-193)', async (path) => {
		// 	mockHasUsers.mockReturnValue(true);
		// 	mockVerifyToken.mockReturnValue(null);
		// 	const event = createMockEvent(path, 'bad-token');
		//
		// 	await expect(handle({ event, resolve: mockResolve })).rejects.toMatchObject({ location: '/login' });
		// 	expect(mockResolve).not.toHaveBeenCalled();
		// });
		// OLD CODE END
		it.each(['/tools', '/tools/subnet-calc', '/tools/ping', '/lookup/dns', '/lookup/whois'])(
			'sends %s to /login without a session (NET-193)',
			async (path) => {
				mockHasUsers.mockReturnValue(true);
				mockVerifyToken.mockReturnValue(null);
				const event = createMockEvent(path, 'bad-token');

				await expect(handle({ event, resolve: mockResolve })).rejects.toMatchObject({ location: '/login' });
				expect(mockResolve).not.toHaveBeenCalled();
			},
		);

		it.each([
			'/api/tools',
			'/api/tools/ping',
			'/api/tools/mac-lookup/aa:bb:cc:dd:ee:ff',
			'/api/lookup/dns/1.1.1.1',
			'/api/lookup/whois/1.1.1.1',
		])('refuses %s without a session (NET-193, NET-197)', async (path) => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue(null);
			const event = createMockEvent(path, 'bad-token');

			await expectUnauthorised(handle({ event, resolve: mockResolve }));
		});

		it('allows the tools with a session', async () => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue({ username: 'admin', role: 'admin' });
			const event = createMockEvent('/api/tools/ping', 'valid-token');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		// OLD CODE START — NET-197: the API paths answer 401 JSON now; split into API calls and /login/x below
		// it.each(['/api/auth/other', '/api/auth/..%2Ftools%2Fping', '/api/auth', '/api/auth/', '/api/auth/me/x', '/api/auth/login/x', '/login/x'])(
		// 	'keeps the rest of /api/auth behind a login, so it never reaches the catch-all proxy: %s',
		// 	async (path) => {
		// 		mockHasUsers.mockReturnValue(true);
		// 		mockVerifyToken.mockReturnValue(null);
		// 		const event = createMockEvent(path);
		//
		// 		await expect(handle({ event, resolve: mockResolve })).rejects.toMatchObject({ location: '/login' });
		// 		expect(mockResolve).not.toHaveBeenCalled();
		// 	},
		// );
		// OLD CODE END
		it.each(['/api/auth/other', '/api/auth/..%2Ftools%2Fping', '/api/auth', '/api/auth/', '/api/auth/me/x', '/api/auth/login/x'])(
			'keeps the rest of /api/auth behind a login, so it never reaches the catch-all proxy: %s',
			async (path) => {
				mockHasUsers.mockReturnValue(true);
				mockVerifyToken.mockReturnValue(null);
				const event = createMockEvent(path);

				await expectUnauthorised(handle({ event, resolve: mockResolve }));
			},
		);

		it('keeps /login/x behind a login', async () => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue(null);
			const event = createMockEvent('/login/x');

			await expect(handle({ event, resolve: mockResolve })).rejects.toMatchObject({ location: '/login' });
			expect(mockResolve).not.toHaveBeenCalled();
		});

		it.each(['/api/auth/login', '/api/auth/logout', '/api/auth/me'])('keeps %s public', async (path) => {
			mockHasUsers.mockReturnValue(true);
			const event = createMockEvent(path);

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		// OLD CODE START — NET-197: '/api/authx' and '/api/auth-tokens' answer 401 JSON now; split below
		// it.each(['/loginx', '/api/authx', '/api/auth-tokens'])(
		// 	'matches whole path segments: %s is not public',
		// 	async (path) => {
		// 		mockHasUsers.mockReturnValue(true);
		// 		mockVerifyToken.mockReturnValue(null);
		// 		const event = createMockEvent(path);
		//
		// 		await expect(handle({ event, resolve: mockResolve })).rejects.toMatchObject({ location: '/login' });
		// 	},
		// );
		// OLD CODE END
		it('matches whole path segments: /loginx is not public', async () => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue(null);
			const event = createMockEvent('/loginx');

			await expect(handle({ event, resolve: mockResolve })).rejects.toMatchObject({ location: '/login' });
		});

		it.each(['/api/authx', '/api/auth-tokens'])('matches whole path segments: %s is not public', async (path) => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue(null);
			const event = createMockEvent(path);

			await expectUnauthorised(handle({ event, resolve: mockResolve }));
		});

		it('keeps /api/auth/* public', async () => {
			mockHasUsers.mockReturnValue(true);
			const event = createMockEvent('/api/auth/login', undefined, undefined, 'POST');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		it('sends the tools to setup during first run, like every other app page', async () => {
			mockHasUsers.mockReturnValue(false);
			const event = createMockEvent('/tools/ping');

			await expect(handle({ event, resolve: mockResolve })).rejects.toMatchObject({ location: '/setup' });
		});

		it('refuses a remote-function call without a session, whatever path it claims', async () => {
			mockHasUsers.mockReturnValue(true);
			const event = { ...createMockEvent('/login'), isRemoteRequest: true };

			const res = await handle({ event, resolve: mockResolve });
			expect(res.status).toBe(401);
			expect(mockResolve).not.toHaveBeenCalled();
		});

		it('lets a remote-function call through with a session', async () => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue({ username: 'admin', role: 'admin' });
			const event = { ...createMockEvent('/devices', 'valid-token'), isRemoteRequest: true };

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		it('keeps first-run paths segment-matched: /setupx goes to setup, not through', async () => {
			mockHasUsers.mockReturnValue(false);
			const event = createMockEvent('/setupx');

			await expect(handle({ event, resolve: mockResolve })).rejects.toMatchObject({ location: '/setup' });
		});

		it('allows /api/health without auth', async () => {
			mockHasUsers.mockReturnValue(true);
			const event = createMockEvent('/api/health');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		it('allows /api/health even when the user store is damaged', async () => {
			mockHasUsers.mockImplementation(() => {
				throw new Error('User store unusable: invalid JSON');
			});
			const event = createMockEvent('/api/health');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});
	});

	describe('first-run redirect', () => {
		it('redirects to /setup when no users exist', async () => {
			mockHasUsers.mockReturnValue(false);
			const event = createMockEvent('/devices');

			await expect(handle({ event, resolve: mockResolve })).rejects.toThrow('redirect');
		});

		// OLD CODE START — NET-229 follow-up: the API paths need the setup cookie now; split below
		// it.each(['/setup', '/api/setup/nics', '/api/bridge/create', '/go-live'])(
		// 	'leaves %s open while no users exist',
		// 	async (path) => {
		// 		mockHasUsers.mockReturnValue(false);
		// 		const event = createMockEvent(path);
		//
		// 		await handle({ event, resolve: mockResolve });
		// 		expect(mockResolve).toHaveBeenCalledWith(event);
		// 	}
		// );
		// OLD CODE END
		// OLD CODE START — review: /go-live needs the setup code too; only /setup stays open
		// it.each(['/setup', '/go-live'])('leaves page %s open while no users exist', async (path) => {
		// 	mockHasUsers.mockReturnValue(false);
		// 	const event = createMockEvent(path);
		//
		// 	await handle({ event, resolve: mockResolve });
		// 	expect(mockResolve).toHaveBeenCalledWith(event);
		// 	expect(mockSetupTokenValid).not.toHaveBeenCalled();
		// });
		// OLD CODE END
		it('leaves /setup open while no users exist, so the code can be typed', async () => {
			mockHasUsers.mockReturnValue(false);
			const event = createMockEvent('/setup');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
			expect(mockSetupTokenValid).not.toHaveBeenCalled();
		});

		it('sends /go-live to /setup until the code is typed', async () => {
			mockHasUsers.mockReturnValue(false);
			mockSetupTokenValid.mockReturnValue(false);
			await expect(handle({ event: createMockEvent('/go-live'), resolve: mockResolve })).rejects.toMatchObject({
				location: '/setup',
			});
			expect(mockResolve).not.toHaveBeenCalled();

			mockSetupTokenValid.mockReturnValue(true);
			const event = createMockEvent('/go-live');
			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		it.each(['/api/setup/nics', '/api/bridge/create'])(
			'answers %s only with the setup cookie while no users exist',
			async (path) => {
				mockHasUsers.mockReturnValue(false);
				mockSetupTokenValid.mockReturnValue(false);
				const res = await handle({ event: createMockEvent(path), resolve: mockResolve });
				expect(res.status).toBe(401);
				expect(await res.json()).toEqual({ error: 'Enter the setup code first.' });
				expect(mockResolve).not.toHaveBeenCalled();

				mockSetupTokenValid.mockReturnValue(true);
				const event = createMockEvent(path);
				await handle({ event, resolve: mockResolve });
				expect(mockResolve).toHaveBeenCalledWith(event);
			}
		);
	});

	describe('setup and bridge routes after setup', () => {
		// OLD CODE START — NET-197: the API paths answer 401 JSON now; split into pages and API calls below
		// it.each(['/setup', '/api/setup/nics', '/api/bridge/teardown', '/go-live'])(
		// 	'requires a session for %s once a user exists',
		// 	async (path) => {
		// 		mockHasUsers.mockReturnValue(true);
		// 		mockVerifyToken.mockReturnValue(null);
		// 		const event = createMockEvent(path);
		//
		// 		await expect(handle({ event, resolve: mockResolve })).rejects.toThrow();
		// 		expect(mockResolve).not.toHaveBeenCalled();
		// 	}
		// );
		// OLD CODE END
		it.each(['/setup', '/go-live'])('requires a session for %s once a user exists', async (path) => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue(null);
			const event = createMockEvent(path);

			await expect(handle({ event, resolve: mockResolve })).rejects.toMatchObject({ location: '/login' });
			expect(mockResolve).not.toHaveBeenCalled();
		});

		it.each(['/api/setup/nics', '/api/bridge/teardown'])('requires a session for %s once a user exists', async (path) => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue(null);
			const event = createMockEvent(path);

			await expectUnauthorised(handle({ event, resolve: mockResolve }));
		});

		it('allows them with a session once a user exists', async () => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue({ username: 'admin', role: 'admin' });
			const event = createMockEvent('/api/bridge/create', 'valid-token');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		it('requires a session when the user store cannot be read', async () => {
			mockHasUsers.mockImplementation(() => {
				throw new Error('User store unusable: EACCES');
			});
			mockVerifyToken.mockReturnValue(null);
			const event = createMockEvent('/api/setup/configure');

			// OLD CODE START — NET-197: an API call answers 401 JSON now, not a redirect
			// await expect(handle({ event, resolve: mockResolve })).rejects.toThrow();
			// expect(mockResolve).not.toHaveBeenCalled();
			// OLD CODE END
			await expectUnauthorised(handle({ event, resolve: mockResolve }));
		});
	});

	describe('DHCP gateway proxy routes', () => {
		// Dedicated +server.ts routes must be gated exactly like the catch-all proxy
		it.each(['/api/capture/dhcp/enable', '/api/capture/dhcp/disable'])(
			'POST %s needs a session after setup and stays closed during first run',
			async (path) => {
				mockHasUsers.mockReturnValue(true);
				mockVerifyToken.mockReturnValue(null);
				// OLD CODE START — NET-197: an API call answers 401 JSON now, after setup and during first run
				// await expect(handle({ event: createMockEvent(path, undefined, undefined, 'POST'), resolve: mockResolve })).rejects.toThrow('redirect');
				//
				// mockHasUsers.mockReturnValue(false);
				// await expect(handle({ event: createMockEvent(path, undefined, undefined, 'POST'), resolve: mockResolve })).rejects.toThrow('redirect');
				// expect(mockResolve).not.toHaveBeenCalled();
				// OLD CODE END
				await expectUnauthorised(handle({ event: createMockEvent(path, undefined, undefined, 'POST'), resolve: mockResolve }));

				mockHasUsers.mockReturnValue(false);
				await expectUnauthorised(handle({ event: createMockEvent(path, undefined, undefined, 'POST'), resolve: mockResolve }));

				mockHasUsers.mockReturnValue(true);
				mockVerifyToken.mockReturnValue({ username: 'admin', role: 'admin' });
				const authed = createMockEvent(path, 'valid-token', undefined, 'POST');
				await handle({ event: authed, resolve: mockResolve });
				expect(mockResolve).toHaveBeenCalledWith(authed);
			}
		);
	});

	describe('auth guard', () => {
		it('redirects unauthenticated users to /login on protected routes', async () => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue(null);
			const event = createMockEvent('/devices');

			await expect(handle({ event, resolve: mockResolve })).rejects.toThrow('redirect');
		});

		it('allows authenticated users through protected routes', async () => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue({ username: 'admin', role: 'admin' });
			const event = createMockEvent('/devices', 'valid-token');

			await handle({ event, resolve: mockResolve });
			expect(event.locals.user).toEqual({ username: 'admin', role: 'admin' });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});
	});

	describe('API calls without a session answer 401 JSON (NET-197)', () => {
		it.each([
			['GET', '/api/suricata/rules/live'],
			['POST', '/api/suricata/rules/custom'],
			['GET', '/api'],
		])('%s %s with an expired session gets 401, not a redirect to /login', async (method, path) => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue(null);
			const event = createMockEvent(path, 'expired-token', undefined, method);

			await expectUnauthorised(handle({ event, resolve: mockResolve }));
		});

		it.each(['GET', 'POST'])('%s to a non-first-run API path during first run gets 401, not a redirect to /setup', async (method) => {
			mockHasUsers.mockReturnValue(false);
			const event = createMockEvent('/api/alerts', undefined, undefined, method);

			await expectUnauthorised(handle({ event, resolve: mockResolve }));
		});

		it('/apix is a page path: it still goes to /login', async () => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue(null);
			const event = createMockEvent('/apix');

			await expect(handle({ event, resolve: mockResolve })).rejects.toMatchObject({ status: 302, location: '/login' });
		});

		it.each([
			[true, '/login'],
			[false, '/setup'],
		])('an /api address opened as a page keeps the redirect (users exist: %s → %s)', async (users, location) => {
			mockHasUsers.mockReturnValue(users);
			mockVerifyToken.mockReturnValue(null);
			const event = createMockEvent('/api/packets/download', 'expired-token', undefined, 'POST', { 'sec-fetch-dest': 'document' });

			await expect(handle({ event, resolve: mockResolve })).rejects.toMatchObject({ status: 302, location });
			expect(mockResolve).not.toHaveBeenCalled();
		});

		it.each([true, false])('a script call (Sec-Fetch-Dest: empty) gets 401 (users exist: %s)', async (users) => {
			mockHasUsers.mockReturnValue(users);
			mockVerifyToken.mockReturnValue(null);
			const event = createMockEvent('/api/packets/download', 'expired-token', undefined, 'GET', { 'sec-fetch-dest': 'empty' });

			await expectUnauthorised(handle({ event, resolve: mockResolve }));
		});

		it('during first run, an API call with a leftover valid cookie gets 401, not a redirect to /setup', async () => {
			mockHasUsers.mockReturnValue(false);
			mockVerifyToken.mockReturnValue({ username: 'admin', role: 'admin' });
			const event = createMockEvent('/api/alerts', 'valid-token');

			await expectUnauthorised(handle({ event, resolve: mockResolve }));
		});
	});

	describe('JWT parsing', () => {
		it('sets event.locals.user when valid token exists', async () => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue({ username: 'admin', role: 'admin' });
			const event = createMockEvent('/tools', 'valid-token');

			await handle({ event, resolve: mockResolve });
			expect(event.locals.user).toEqual({ username: 'admin', role: 'admin' });
		});

		it('does not set user for invalid token', async () => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue(null);
			// OLD CODE: const event = createMockEvent('/tools', 'bad-token'); (NET-193: /tools needs a login)
			const event = createMockEvent('/login', 'bad-token');

			await handle({ event, resolve: mockResolve });
			expect(event.locals.user).toBeUndefined();
		});
	});

	describe('login redirect for authenticated users', () => {
		it('redirects authenticated user away from /login', async () => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue({ username: 'admin', role: 'admin' });
			const event = createMockEvent('/login', 'valid-token');

			await expect(handle({ event, resolve: mockResolve })).rejects.toThrow('redirect');
		});
	});

	// NET-257: SameSite=lax lets another site's link carry the owner's cookie to any /api route
	describe('/api requests another site starts (Sec-Fetch-Site)', () => {
		/** A signed-in request, with the route SvelteKit would have matched for it. */
		function signedIn(pathname: string, routeId: string | null, site?: string, method = 'GET') {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue({ username: 'admin', role: 'admin' });
			const headers: Record<string, string> = site ? { 'sec-fetch-site': site } : {};
			return { ...createMockEvent(pathname, 'valid-token', undefined, method, headers), route: { id: routeId } };
		}

		const REFUSED = [
			['/api/pcap/download?filter=tcp', '/api/[...path]'],
			['/api/threats/beaconing', '/api/threats/beaconing'],
			// a decoded ../ in an explicit route's param once steered it to the download
			['/api/logs/fields/..%2F..%2Fpcap%2Fdownload', '/api/logs/fields/[log_type]'],
			// SvelteKit decodes the path for routing, so an encoded prefix still reaches /api routes
			['/%61pi/pcap/download?filter=tcp', '/api/[...path]'],
			['/%61pi/threats/beaconing', '/api/threats/beaconing'],
		] as const;

		it.each(REFUSED.flatMap(([path, id]) => ['cross-site', 'same-site', 'none'].map((site) => [path, id, site])))(
			'refuses %s (route %s) from a %s request without running it',
			async (path, id, site) => {
				const res = await handle({ event: signedIn(path, id, site), resolve: mockResolve });
				expect(res.status).toBe(403);
				expect(await res.json()).toEqual({ error: 'Open this from NetTap itself.' });
				expect(mockResolve).not.toHaveBeenCalled();
			},
		);

		it('refuses a POST another site starts', async () => {
			const event = signedIn('/api/settings/bandwidth-cap', '/api/[...path]', 'cross-site', 'POST');
			const res = await handle({ event, resolve: mockResolve });
			expect(res.status).toBe(403);
			expect(mockResolve).not.toHaveBeenCalled();
		});

		it.each([['same-origin'], [undefined]])('lets a %s request through', async (site) => {
			const event = signedIn('/api/pcap/download?filter=tcp', '/api/[...path]', site);
			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		it('leaves pages and public auth routes to their own rules', async () => {
			// a page may be linked from anywhere; nginx's auth_request forwards the browser's headers to /api/auth/me
			for (const [path, id] of [['/alerts', '/alerts'], ['/api/auth/me', '/api/auth/me']] as const) {
				mockResolve.mockClear();
				const event = signedIn(path, id, 'cross-site');
				await handle({ event, resolve: mockResolve });
				expect(mockResolve).toHaveBeenCalledWith(event);
			}
		});
	});
});
