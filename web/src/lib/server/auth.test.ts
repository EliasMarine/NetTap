import { describe, it, expect, vi, beforeEach } from 'vitest';

const mocks = vi.hoisted(() => ({
	existsSync: vi.fn().mockReturnValue(false),
	readFileSync: vi.fn().mockReturnValue('{"users":[]}'),
	writeFileSync: vi.fn(),
	mkdirSync: vi.fn(),
	argonHash: vi.fn().mockResolvedValue('$argon2id$mock-hash'),
	argonVerify: vi.fn().mockResolvedValue(false),
	jwtSign: vi.fn().mockReturnValue('mock-jwt-token'),
	jwtVerify: vi.fn().mockReturnValue({ username: 'admin', role: 'admin' }),
}));

vi.mock('fs', () => {
	const fsMock = {
		existsSync: mocks.existsSync,
		readFileSync: mocks.readFileSync,
		writeFileSync: mocks.writeFileSync,
		mkdirSync: mocks.mkdirSync,
	};
	return { ...fsMock, default: fsMock };
});

vi.mock('argon2', () => ({
	argon2id: 2,
	hash: mocks.argonHash,
	verify: mocks.argonVerify,
}));

vi.mock('jsonwebtoken', () => ({
	default: {
		sign: mocks.jwtSign,
		verify: mocks.jwtVerify,
	},
}));

import {
	hashPassword,
	verifyPassword,
	generateToken,
	verifyToken,
	hasUsers,
	getUser,
	createUser,
	updatePassword,
} from './auth';

describe('auth server module', () => {
	beforeEach(() => {
		mocks.existsSync.mockReset().mockReturnValue(false);
		mocks.readFileSync.mockReset().mockReturnValue('{"users":[]}');
		mocks.writeFileSync.mockReset();
		mocks.mkdirSync.mockReset();
		mocks.argonHash.mockReset().mockResolvedValue('$argon2id$mock-hash');
		mocks.argonVerify.mockReset().mockResolvedValue(false);
		mocks.jwtSign.mockReset().mockReturnValue('mock-jwt-token');
		mocks.jwtVerify.mockReset().mockReturnValue({ username: 'admin', role: 'admin' });
	});

	describe('hashPassword', () => {
		it('returns a hashed string', async () => {
			const hash = await hashPassword('mypassword');
			expect(hash).toBe('$argon2id$mock-hash');
			expect(mocks.argonHash).toHaveBeenCalledWith('mypassword', expect.objectContaining({ type: 2 }));
		});
	});

	describe('verifyPassword', () => {
		it('returns true for matching password', async () => {
			mocks.argonVerify.mockResolvedValue(true);
			const result = await verifyPassword('correct', '$argon2id$somehash');
			expect(result).toBe(true);
		});

		it('returns false for non-matching password', async () => {
			mocks.argonVerify.mockResolvedValue(false);
			const result = await verifyPassword('wrong', '$argon2id$somehash');
			expect(result).toBe(false);
		});
	});

	describe('generateToken', () => {
		it('returns a JWT string', () => {
			const token = generateToken({ username: 'admin', role: 'admin' });
			expect(token).toBe('mock-jwt-token');
			expect(mocks.jwtSign).toHaveBeenCalledWith(
				{ username: 'admin', role: 'admin' },
				expect.any(String),
				expect.objectContaining({ expiresIn: '24h' })
			);
		});
	});

	describe('verifyToken', () => {
		it('returns payload for valid token', () => {
			mocks.jwtVerify.mockReturnValue({ username: 'admin', role: 'admin' });
			const payload = verifyToken('valid-token');
			expect(payload).toEqual({ username: 'admin', role: 'admin' });
		});

		it('returns null for invalid token', () => {
			mocks.jwtVerify.mockImplementation(() => {
				throw new Error('invalid');
			});
			const payload = verifyToken('bad-token');
			expect(payload).toBeNull();
		});
	});

	describe('hasUsers', () => {
		it('returns false when no users file exists', () => {
			mocks.readFileSync.mockImplementation(() => {
				throw new Error('ENOENT');
			});
			expect(hasUsers()).toBe(false);
		});

		it('returns false when users array is empty', () => {
			mocks.readFileSync.mockReturnValue('{"users":[]}');
			expect(hasUsers()).toBe(false);
		});

		it('returns true when users exist', () => {
			mocks.readFileSync.mockReturnValue(
				JSON.stringify({
					users: [{ username: 'admin', passwordHash: 'hash', role: 'admin', createdAt: '', updatedAt: '' }],
				})
			);
			expect(hasUsers()).toBe(true);
		});
	});

	describe('getUser', () => {
		it('returns undefined when user not found', () => {
			mocks.readFileSync.mockReturnValue('{"users":[]}');
			expect(getUser('nonexistent')).toBeUndefined();
		});

		it('returns user when found', () => {
			const user = { username: 'admin', passwordHash: 'hash', role: 'admin', createdAt: '2025-01-01', updatedAt: '2025-01-01' };
			mocks.readFileSync.mockReturnValue(JSON.stringify({ users: [user] }));
			expect(getUser('admin')).toEqual(user);
		});
	});

	describe('createUser', () => {
		it('creates a new user and writes to file', async () => {
			mocks.readFileSync.mockReturnValue('{"users":[]}');
			mocks.existsSync.mockReturnValue(true);

			const user = await createUser('newuser', 'password123');
			expect(user.username).toBe('newuser');
			expect(user.passwordHash).toBe('$argon2id$mock-hash');
			expect(user.role).toBe('admin');
			expect(mocks.writeFileSync).toHaveBeenCalled();
		});

		it('throws if user already exists', async () => {
			mocks.readFileSync.mockReturnValue(
				JSON.stringify({
					users: [{ username: 'existing', passwordHash: 'hash', role: 'admin', createdAt: '', updatedAt: '' }],
				})
			);
			mocks.existsSync.mockReturnValue(true);

			await expect(createUser('existing', 'pass')).rejects.toThrow('already exists');
		});
	});

	describe('updatePassword', () => {
		it('updates the password hash for an existing user', async () => {
			mocks.readFileSync.mockReturnValue(
				JSON.stringify({
					users: [{ username: 'admin', passwordHash: 'old-hash', role: 'admin', createdAt: '2025-01-01', updatedAt: '2025-01-01' }],
				})
			);
			mocks.existsSync.mockReturnValue(true);

			await updatePassword('admin', 'newpassword');
			expect(mocks.writeFileSync).toHaveBeenCalled();
		});

		it('throws if user not found', async () => {
			mocks.readFileSync.mockReturnValue('{"users":[]}');
			await expect(updatePassword('ghost', 'pass')).rejects.toThrow('not found');
		});
	});
});
