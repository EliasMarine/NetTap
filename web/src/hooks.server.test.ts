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

function createMockEvent(pathname: string, token?: string, user?: any) {
	return {
		url: new URL(`http://localhost${pathname}`),
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
		it('allows /setup without auth', async () => {
			mockHasUsers.mockReturnValue(true);
			const event = createMockEvent('/setup');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		it('allows /login without auth', async () => {
			mockHasUsers.mockReturnValue(true);
			const event = createMockEvent('/login');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		it('allows /tools without auth', async () => {
			mockHasUsers.mockReturnValue(true);
			const event = createMockEvent('/tools/subnet-calc');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		it('allows /api/setup endpoints without auth', async () => {
			mockHasUsers.mockReturnValue(true);
			const event = createMockEvent('/api/setup/nics');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		it('allows /go-live without auth', async () => {
			mockHasUsers.mockReturnValue(true);
			const event = createMockEvent('/go-live');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalledWith(event);
		});

		it('allows /api/health without auth', async () => {
			mockHasUsers.mockReturnValue(true);
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

		it('does not redirect public paths even with no users', async () => {
			mockHasUsers.mockReturnValue(false);
			const event = createMockEvent('/setup');

			await handle({ event, resolve: mockResolve });
			expect(mockResolve).toHaveBeenCalled();
		});
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
			const event = createMockEvent('/tools', 'bad-token');

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
