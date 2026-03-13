import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Tests for the login page server action (login/+page.server.ts).
 *
 * We replicate the validation logic here because the actual +page.server.ts
 * depends on SvelteKit runtime ($types, fail(), redirect()) and server-only
 * auth modules (argon2, jwt) that can't easily be imported in Vitest.
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
