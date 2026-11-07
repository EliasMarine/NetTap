import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { redirect } from '@sveltejs/kit';

// Mock $lib/server/auth.js
const mockVerifyToken = vi.fn();
const mockHasUsers = vi.fn();

vi.mock('$lib/server/auth.js', () => ({
	verifyToken: mockVerifyToken,
	hasUsers: mockHasUsers,
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

function createMockEvent(pathname: string, token?: string, user?: any, method = 'GET') {
	const url = new URL(`http://localhost${pathname}`);
	return {
		url,
		request: new Request(url, { method }),
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

	beforeEach(async () => {
		vi.resetModules();
		mockVerifyToken.mockReset();
		mockHasUsers.mockReset();
		mockResolve.mockClear();

		// Re-mock after resetModules
		vi.mock('$lib/server/auth.js', () => ({
			verifyToken: mockVerifyToken,
			hasUsers: mockHasUsers,
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

		it.each([
			'/tools/subnet-calc',
			'/tools/ping',
			'/lookup/whois',
			'/api/tools/ping',
			'/api/tools/mac-lookup/aa:bb:cc:dd:ee:ff',
			'/api/lookup/dns/1.1.1.1',
			'/api/lookup/whois/1.1.1.1',
		])('sends %s to /login without a session (NET-193)', async (path) => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue(null);
			const event = createMockEvent(path);

			await expect(handle({ event, resolve: mockResolve })).rejects.toMatchObject({ location: '/login' });
			expect(mockResolve).not.toHaveBeenCalled();
		});

		it('allows the tools with a session', async () => {
			mockHasUsers.mockReturnValue(true);
			mockVerifyToken.mockReturnValue({ username: 'admin', role: 'admin' });
			const event = createMockEvent('/api/tools/ping', 'valid-token');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		it.each(['/loginx', '/api/authx', '/api/auth-tokens'])(
			'matches whole path segments: %s is not public',
			async (path) => {
				mockHasUsers.mockReturnValue(true);
				mockVerifyToken.mockReturnValue(null);
				const event = createMockEvent(path);

				await expect(handle({ event, resolve: mockResolve })).rejects.toMatchObject({ location: '/login' });
			},
		);

		it('keeps /api/auth/* public', async () => {
			mockHasUsers.mockReturnValue(true);
			const event = createMockEvent('/api/auth/login', undefined, undefined, 'POST');

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

		it.each(['/setup', '/api/setup/nics', '/api/bridge/create', '/go-live'])(
			'leaves %s open while no users exist',
			async (path) => {
				mockHasUsers.mockReturnValue(false);
				const event = createMockEvent(path);

				await handle({ event, resolve: mockResolve });
				expect(mockResolve).toHaveBeenCalledWith(event);
			}
		);
	});

	describe('setup and bridge routes after setup', () => {
		it.each(['/setup', '/api/setup/nics', '/api/bridge/teardown', '/go-live'])(
			'requires a session for %s once a user exists',
			async (path) => {
				mockHasUsers.mockReturnValue(true);
				mockVerifyToken.mockReturnValue(null);
				const event = createMockEvent(path);

				await expect(handle({ event, resolve: mockResolve })).rejects.toThrow();
				expect(mockResolve).not.toHaveBeenCalled();
			}
		);

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

			await expect(handle({ event, resolve: mockResolve })).rejects.toThrow();
			expect(mockResolve).not.toHaveBeenCalled();
		});
	});

	describe('DHCP gateway proxy routes', () => {
		// Dedicated +server.ts routes must be gated exactly like the catch-all proxy
		it.each(['/api/capture/dhcp/enable', '/api/capture/dhcp/disable'])(
			'POST %s needs a session after setup and stays closed during first run',
			async (path) => {
				mockHasUsers.mockReturnValue(true);
				mockVerifyToken.mockReturnValue(null);
				await expect(handle({ event: createMockEvent(path, undefined, undefined, 'POST'), resolve: mockResolve })).rejects.toThrow('redirect');

				mockHasUsers.mockReturnValue(false);
				await expect(handle({ event: createMockEvent(path, undefined, undefined, 'POST'), resolve: mockResolve })).rejects.toThrow('redirect');
				expect(mockResolve).not.toHaveBeenCalled();

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
});
