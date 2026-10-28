import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Tests for the setup page server action (setup/+page.server.ts).
 *
 * Replicates the createAdmin validation logic since the actual file
 * depends on SvelteKit runtime imports and server-only auth modules.
 */

const mockHasUsers = vi.fn();
const mockCreateUser = vi.fn();

interface AdminInput {
	username?: string;
	password?: string;
	confirmPassword?: string;
}

interface ActionResult {
	status?: number;
	error?: string;
	username?: string;
	success?: boolean;
	redirect?: string;
}

/**
 * Reproduces the createAdmin validation logic from +page.server.ts
 */
async function createAdminAction(input: AdminInput): Promise<ActionResult> {
	// If users already exist, redirect to login
	if (mockHasUsers()) {
		return { redirect: '/login' };
	}

	const username = input.username?.trim();
	const password = input.password;
	const confirmPassword = input.confirmPassword;

	if (!username || !password || !confirmPassword) {
		return {
			status: 400,
			error: 'All fields are required.',
			username: username ?? '',
		};
	}

	if (username.length < 3) {
		return {
			status: 400,
			error: 'Username must be at least 3 characters.',
			username,
		};
	}

	if (!/^[a-zA-Z0-9_-]+$/.test(username)) {
		return {
			status: 400,
			error: 'Username can only contain letters, numbers, hyphens, and underscores.',
			username,
		};
	}

	if (password.length < 8) {
		return {
			status: 400,
			error: 'Password must be at least 8 characters.',
			username,
		};
	}

	if (!/[A-Z]/.test(password)) {
		return {
			status: 400,
			error: 'Password must contain at least one uppercase letter.',
			username,
		};
	}

	if (!/[a-z]/.test(password)) {
		return {
			status: 400,
			error: 'Password must contain at least one lowercase letter.',
			username,
		};
	}

	if (!/[0-9]/.test(password)) {
		return {
			status: 400,
			error: 'Password must contain at least one number.',
			username,
		};
	}

	if (password !== confirmPassword) {
		return {
			status: 400,
			error: 'Passwords do not match.',
			username,
		};
	}

	try {
		await mockCreateUser(username, password, 'admin');
	} catch (err) {
		return {
			status: 500,
			error: err instanceof Error ? err.message : 'Failed to create user.',
			username,
		};
	}

	return { success: true, username };
}

beforeEach(() => {
	mockHasUsers.mockReset();
	mockCreateUser.mockReset();
	mockHasUsers.mockReturnValue(false);
	mockCreateUser.mockResolvedValue(undefined);
});

describe('Setup createAdmin — Guard', () => {
	it('redirects to /login when users already exist', async () => {
		mockHasUsers.mockReturnValue(true);
		const result = await createAdminAction({ username: 'admin', password: 'Test1234', confirmPassword: 'Test1234' });
		expect(result.redirect).toBe('/login');
		expect(mockCreateUser).not.toHaveBeenCalled();
	});
});

describe('Setup createAdmin — Required Fields', () => {
	it('rejects missing username', async () => {
		const result = await createAdminAction({ password: 'Test1234', confirmPassword: 'Test1234' });
		expect(result.status).toBe(400);
		expect(result.error).toContain('required');
	});

	it('rejects missing password', async () => {
		const result = await createAdminAction({ username: 'admin', confirmPassword: 'Test1234' });
		expect(result.status).toBe(400);
		expect(result.error).toContain('required');
	});

	it('rejects missing confirmPassword', async () => {
		const result = await createAdminAction({ username: 'admin', password: 'Test1234' });
		expect(result.status).toBe(400);
		expect(result.error).toContain('required');
	});
});

describe('Setup createAdmin — Username Validation', () => {
	it('rejects username shorter than 3 characters', async () => {
		const result = await createAdminAction({ username: 'ab', password: 'Test1234', confirmPassword: 'Test1234' });
		expect(result.status).toBe(400);
		expect(result.error).toContain('3 characters');
	});

	it('rejects username with special characters', async () => {
		const result = await createAdminAction({ username: 'admin@!', password: 'Test1234', confirmPassword: 'Test1234' });
		expect(result.status).toBe(400);
		expect(result.error).toContain('letters, numbers');
	});

	it('accepts username with hyphens and underscores', async () => {
		const result = await createAdminAction({ username: 'my-admin_1', password: 'Test1234', confirmPassword: 'Test1234' });
		expect(result.success).toBe(true);
	});
});

describe('Setup createAdmin — Password Validation', () => {
	it('rejects password shorter than 8 characters', async () => {
		const result = await createAdminAction({ username: 'admin', password: 'Test12', confirmPassword: 'Test12' });
		expect(result.status).toBe(400);
		expect(result.error).toContain('8 characters');
	});

	it('rejects password without uppercase letter', async () => {
		const result = await createAdminAction({ username: 'admin', password: 'test1234', confirmPassword: 'test1234' });
		expect(result.status).toBe(400);
		expect(result.error).toContain('uppercase');
	});

	it('rejects password without lowercase letter', async () => {
		const result = await createAdminAction({ username: 'admin', password: 'TEST1234', confirmPassword: 'TEST1234' });
		expect(result.status).toBe(400);
		expect(result.error).toContain('lowercase');
	});

	it('rejects password without number', async () => {
		const result = await createAdminAction({ username: 'admin', password: 'TestPass', confirmPassword: 'TestPass' });
		expect(result.status).toBe(400);
		expect(result.error).toContain('number');
	});

	it('rejects mismatched passwords', async () => {
		const result = await createAdminAction({ username: 'admin', password: 'Test1234', confirmPassword: 'Test5678' });
		expect(result.status).toBe(400);
		expect(result.error).toContain('do not match');
	});
});

describe('Setup createAdmin — Success', () => {
	it('creates user with valid input', async () => {
		const result = await createAdminAction({ username: 'admin', password: 'Test1234', confirmPassword: 'Test1234' });
		expect(result.success).toBe(true);
		expect(result.username).toBe('admin');
		expect(mockCreateUser).toHaveBeenCalledWith('admin', 'Test1234', 'admin');
	});

	it('handles createUser failure', async () => {
		mockCreateUser.mockRejectedValue(new Error('Database write failed'));
		const result = await createAdminAction({ username: 'admin', password: 'Test1234', confirmPassword: 'Test1234' });
		expect(result.status).toBe(500);
		expect(result.error).toContain('Database write failed');
	});
});
