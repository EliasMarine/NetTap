import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Tests for the login page server action (login/+page.server.ts).
 *
 * We replicate the validation logic here because the actual +page.server.ts
 * depends on SvelteKit runtime ($types, fail(), redirect()) and server-only
 * auth modules (argon2, jwt) that can't easily be imported in Vitest.
 * The throttling suite at the bottom imports the real action with those mocked.
 */

// Mock auth functions
const mockGetUser = vi.fn();
const mockVerifyPassword = vi.fn();
const mockGenerateToken = vi.fn();
const mockSetAuthCookie = vi.fn();

interface FormInput {
	username?: string;
	password?: string;
}

interface ActionResult {
	status?: number;
	error?: string;
	username?: string;
	redirect?: string;
}

/**
 * Reproduces the login validation logic from +page.server.ts
 */
async function loginAction(input: FormInput): Promise<ActionResult> {
	const username = input.username?.trim();
	const password = input.password;

	if (!username || !password) {
		return {
			status: 400,
			error: 'Username and password are required.',
			username: username ?? '',
		};
	}

	const user = mockGetUser(username);
	if (!user) {
		return {
			status: 401,
			error: 'Invalid username or password.',
			username,
		};
	}

	const valid = await mockVerifyPassword(password, user.passwordHash);
	if (!valid) {
		return {
			status: 401,
			error: 'Invalid username or password.',
			username,
		};
	}

	const token = mockGenerateToken({ username: user.username, role: user.role });
	mockSetAuthCookie(token);

	return { redirect: '/' };
}

beforeEach(() => {
	mockGetUser.mockReset();
	mockVerifyPassword.mockReset();
	mockGenerateToken.mockReset();
	mockSetAuthCookie.mockReset();
});

describe('Login Action — Validation', () => {
	it('rejects empty username', async () => {
		const result = await loginAction({ username: '', password: 'Password1' });
		expect(result.status).toBe(400);
		expect(result.error).toContain('required');
	});

	it('rejects empty password', async () => {
		const result = await loginAction({ username: 'admin', password: '' });
		expect(result.status).toBe(400);
		expect(result.error).toContain('required');
	});

	it('rejects missing both fields', async () => {
		const result = await loginAction({});
		expect(result.status).toBe(400);
		expect(result.error).toContain('required');
	});

	it('trims whitespace from username', async () => {
		mockGetUser.mockReturnValue(null);
		const result = await loginAction({ username: '  admin  ', password: 'Password1' });
		expect(mockGetUser).toHaveBeenCalledWith('admin');
		expect(result.status).toBe(401);
	});
});

describe('Login Action — Authentication', () => {
	it('rejects unknown user', async () => {
		mockGetUser.mockReturnValue(null);
		const result = await loginAction({ username: 'unknown', password: 'Password1' });
		expect(result.status).toBe(401);
		expect(result.error).toContain('Invalid');
	});

	it('rejects wrong password', async () => {
		mockGetUser.mockReturnValue({ username: 'admin', passwordHash: 'hash', role: 'admin' });
		mockVerifyPassword.mockResolvedValue(false);

		const result = await loginAction({ username: 'admin', password: 'WrongPass1' });
		expect(result.status).toBe(401);
		expect(result.error).toContain('Invalid');
	});

	it('returns same error for unknown user and wrong password (no user enumeration)', async () => {
		mockGetUser.mockReturnValue(null);
		const unknownResult = await loginAction({ username: 'unknown', password: 'Pass1' });

		mockGetUser.mockReturnValue({ username: 'admin', passwordHash: 'hash', role: 'admin' });
		mockVerifyPassword.mockResolvedValue(false);
		const wrongPassResult = await loginAction({ username: 'admin', password: 'WrongPass1' });

		expect(unknownResult.error).toBe(wrongPassResult.error);
	});

	it('succeeds with correct credentials', async () => {
		mockGetUser.mockReturnValue({ username: 'admin', passwordHash: 'hash', role: 'admin' });
		mockVerifyPassword.mockResolvedValue(true);
		mockGenerateToken.mockReturnValue('jwt-token-123');

		const result = await loginAction({ username: 'admin', password: 'CorrectPass1' });
		expect(result.redirect).toBe('/');
		expect(mockGenerateToken).toHaveBeenCalledWith({ username: 'admin', role: 'admin' });
		expect(mockSetAuthCookie).toHaveBeenCalledWith('jwt-token-123');
	});
});

// ----- The real form action (CR-034: throttling + timing) -----

const real = vi.hoisted(() => ({
	getUser: vi.fn(),
	verifyPassword: vi.fn(),
	hashPassword: vi.fn(),
	generateToken: vi.fn(),
	setAuthCookie: vi.fn(),
}));

vi.mock('$lib/server/auth.js', () => ({
	getUser: real.getUser,
	verifyPassword: real.verifyPassword,
	hashPassword: real.hashPassword,
	generateToken: real.generateToken,
}));
vi.mock('$lib/server/middleware.js', () => ({ setAuthCookie: real.setAuthCookie }));

describe('Login form action — throttling (real +page.server.ts)', () => {
	let actions: typeof import('./+page.server').actions;

	beforeEach(async () => {
		vi.resetModules(); // fresh limiter state per test
		({ actions } = await import('./+page.server'));
		real.getUser.mockReset().mockImplementation((name: string) =>
			name === 'admin' ? { username: 'admin', passwordHash: '$argon2id$real', role: 'admin' } : undefined
		);
		real.verifyPassword.mockReset().mockImplementation(async (pw: string) => pw === 'right');
		real.hashPassword.mockReset().mockResolvedValue('$argon2id$dummy');
		real.generateToken.mockReset().mockReturnValue('jwt');
		real.setAuthCookie.mockReset();
	});

	async function submit(username: string, password: string, ip = '192.168.1.10') {
		const form = new FormData();
		form.set('username', username);
		form.set('password', password);
		const request = new Request('http://localhost/login', { method: 'POST', body: form });
		try {
			return await actions.default({ request, getClientAddress: () => ip } as never);
		} catch (thrown) {
			return thrown; // redirect() throws
		}
	}

	it('redirects home on the right password', async () => {
		expect(await submit('admin', 'right')).toMatchObject({ status: 302, location: '/' });
		expect(real.setAuthCookie).toHaveBeenCalledWith(expect.anything(), 'jwt');
	});

	it('shows a friendly 429 error on the form after 5 attempts a minute from one client', async () => {
		for (let i = 0; i < 5; i++) {
			expect(await submit(`user${i}`, 'wrong')).toMatchObject({ status: 401 });
		}

		const result = await submit('admin', 'right');

		expect(result).toMatchObject({
			status: 429,
			data: { error: 'Too many login attempts. Please wait 60 seconds and try again.', username: 'admin' },
		});
		expect(real.setAuthCookie).not.toHaveBeenCalled();
	});

	it('locks a username after 5 failures even when each comes from a different client', async () => {
		for (let i = 0; i < 5; i++) await submit('admin', 'wrong', `10.0.0.${i}`);

		expect(await submit('admin', 'right', '10.0.1.1')).toMatchObject({ status: 429 });
	});

	it('runs a password verify for unknown usernames so timing does not reveal them', async () => {
		expect(await submit('ghost', 'right')).toMatchObject({ status: 401 });
		expect(real.verifyPassword).toHaveBeenCalledWith('right', '$argon2id$dummy');
	});
});
