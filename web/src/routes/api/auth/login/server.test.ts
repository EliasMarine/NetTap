import { describe, it, expect, vi, beforeEach } from 'vitest';

const mocks = vi.hoisted(() => ({
	getUser: vi.fn(),
	verifyPassword: vi.fn(),
	hashPassword: vi.fn(),
	generateToken: vi.fn(),
	setAuthCookie: vi.fn(),
}));

vi.mock('$lib/server/auth.js', () => ({
	getUser: mocks.getUser,
	verifyPassword: mocks.verifyPassword,
	hashPassword: mocks.hashPassword,
	generateToken: mocks.generateToken,
}));
vi.mock('$lib/server/middleware.js', () => ({ setAuthCookie: mocks.setAuthCookie }));

const ADMIN = { username: 'admin', passwordHash: '$argon2id$real', role: 'admin' };

let POST: typeof import('./+server').POST;

beforeEach(async () => {
	vi.resetModules(); // fresh limiter state per test
	({ POST } = await import('./+server'));
	mocks.getUser.mockReset().mockImplementation((name: string) => (name === 'admin' ? ADMIN : undefined));
	mocks.verifyPassword.mockReset().mockImplementation(async (pw: string) => pw === 'right');
	mocks.hashPassword.mockReset().mockResolvedValue('$argon2id$dummy');
	mocks.generateToken.mockReset().mockReturnValue('jwt');
	mocks.setAuthCookie.mockReset();
});

async function post(body: unknown, ip = '192.168.1.10') {
	const request = new Request('http://localhost/api/auth/login', {
		method: 'POST',
		body: JSON.stringify(body),
	});
	const res = await POST({ request, getClientAddress: () => ip } as unknown as Parameters<typeof POST>[0]);
	return { status: res.status, headers: res.headers, body: await res.json() };
}

describe('POST /api/auth/login', () => {
	it('logs in with the right password', async () => {
		const { status, body } = await post({ username: 'admin', password: 'right' });

		expect(status).toBe(200);
		expect(body).toEqual({ success: true, user: { username: 'admin', role: 'admin' } });
		expect(mocks.setAuthCookie).toHaveBeenCalledWith(expect.anything(), 'jwt');
	});

	it('rejects non-string credentials with 400 instead of throwing', async () => {
		const { status, body } = await post({ username: 42, password: ['x'] });

		expect(status).toBe(400);
		expect(body.error).toBe('Username and password are required.');
	});

	it('hashes for unknown usernames too, so timing does not reveal them', async () => {
		const { status } = await post({ username: 'ghost', password: 'right' });

		expect(status).toBe(401);
		expect(mocks.verifyPassword).toHaveBeenCalledWith('right', '$argon2id$dummy');
	});

	it('returns 429 with Retry-After once a client exceeds 5 attempts a minute', async () => {
		for (let i = 0; i < 5; i++) {
			expect((await post({ username: `user${i}`, password: 'wrong' })).status).toBe(401);
		}

		const { status, headers, body } = await post({ username: 'admin', password: 'right' });

		expect(status).toBe(429);
		expect(headers.get('Retry-After')).toBe('60');
		expect(body.error).toMatch(/^Too many login attempts\. Please wait/);
	});

	it('does not lock out other clients when one client is throttled', async () => {
		for (let i = 0; i < 6; i++) await post({ username: `user${i}`, password: 'wrong' }, '192.168.1.66');

		expect((await post({ username: 'admin', password: 'right' }, '192.168.1.10')).status).toBe(200);
	});

	it('shares the username lockout with the login form', async () => {
		const { actions } = await import('../../../login/+page.server');
		for (let i = 0; i < 5; i++) {
			const form = new FormData();
			form.set('username', 'admin');
			form.set('password', 'wrong');
			const request = new Request('http://localhost/login', { method: 'POST', body: form });
			await actions.default({ request, getClientAddress: () => `10.0.0.${i}` } as never);
		}

		expect((await post({ username: 'admin', password: 'right' }, '10.0.1.1')).status).toBe(429);
	});
});
