import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const mocks = vi.hoisted(() => ({
	getUser: vi.fn(),
	verifyPassword: vi.fn(),
	hashPassword: vi.fn(),
}));

vi.mock('./auth.js', () => mocks);

const ADMIN = { username: 'admin', passwordHash: '$argon2id$real', role: 'admin' };
const MINUTE = 60_000;

let attemptLogin: typeof import('./login.js').attemptLogin;

beforeEach(async () => {
	vi.useFakeTimers();
	vi.resetModules(); // fresh limiter maps per test
	({ attemptLogin } = await import('./login.js'));
	mocks.getUser.mockReset().mockImplementation((name: string) => (name === 'admin' ? ADMIN : undefined));
	mocks.verifyPassword.mockReset().mockImplementation(async (pw: string) => pw === 'right');
	mocks.hashPassword.mockReset().mockResolvedValue('$argon2id$dummy');
});

afterEach(() => {
	vi.useRealTimers();
});

/** Fail `n` times for `username`, each from its own IP so only the username limit applies. */
async function failFromManyIps(username: string, n: number) {
	for (let i = 0; i < n; i++) {
		const r = await attemptLogin(`10.1.${n}.${i}`, username, 'wrong');
		expect(r).toMatchObject({ ok: false, status: 401 });
	}
}

describe('attemptLogin — credentials', () => {
	it('returns the user for the right password', async () => {
		const r = await attemptLogin('10.0.0.1', 'admin', 'right');
		expect(r).toEqual({ ok: true, user: ADMIN });
	});

	it('returns 401 for a wrong password', async () => {
		const r = await attemptLogin('10.0.0.1', 'admin', 'wrong');
		expect(r).toEqual({ ok: false, status: 401, error: 'Invalid username or password.' });
	});

	it('runs a dummy verify for unknown usernames so timing does not reveal them', async () => {
		const r = await attemptLogin('10.0.0.1', 'ghost', 'right');

		expect(r).toEqual({ ok: false, status: 401, error: 'Invalid username or password.' });
		expect(mocks.verifyPassword).toHaveBeenCalledWith('right', '$argon2id$dummy');
	});

	it('hashes the dummy password only once', async () => {
		await attemptLogin('10.0.0.1', 'ghost1', 'x');
		await attemptLogin('10.0.0.2', 'ghost2', 'x');
		expect(mocks.hashPassword).toHaveBeenCalledTimes(1);
	});
});

describe('attemptLogin — per-IP limit', () => {
	it('allows 5 attempts a minute per IP, then 429 without hashing', async () => {
		for (let i = 0; i < 5; i++) {
			expect((await attemptLogin('10.0.0.1', `user${i}`, 'wrong')).ok).toBe(false);
		}
		mocks.verifyPassword.mockClear();

		const r = await attemptLogin('10.0.0.1', 'admin', 'right');

		expect(r).toMatchObject({ ok: false, status: 429, retryAfter: 60 });
		expect(r.ok === false && r.error).toBe('Too many login attempts. Please wait 60 seconds and try again.');
		expect(mocks.verifyPassword).not.toHaveBeenCalled();
	});

	it('keeps clients in separate buckets', async () => {
		for (let i = 0; i < 5; i++) await attemptLogin('10.0.0.1', `user${i}`, 'wrong');

		expect(await attemptLogin('10.0.0.2', 'admin', 'right')).toMatchObject({ ok: true });
	});

	it('lets the IP back in after the window', async () => {
		for (let i = 0; i < 5; i++) await attemptLogin('10.0.0.1', `user${i}`, 'wrong');
		vi.advanceTimersByTime(MINUTE);

		expect(await attemptLogin('10.0.0.1', 'admin', 'right')).toMatchObject({ ok: true });
	});

	it('stays bounded: old IP entries are evicted past 10,000 clients', async () => {
		for (let i = 0; i < 5; i++) await attemptLogin('10.0.0.1', 'admin', 'right');
		expect(await attemptLogin('10.0.0.1', 'admin', 'right')).toMatchObject({ status: 429 });

		for (let i = 0; i < 10_000; i++) {
			await attemptLogin(`172.16.${i >> 8}.${i & 255}`, 'admin', 'right');
		}

		expect(await attemptLogin('10.0.0.1', 'admin', 'right')).toMatchObject({ ok: true });
	});
});

describe('attemptLogin — per-username backoff', () => {
	it('locks a username for 1 minute after 5 failures, from any IP', async () => {
		await failFromManyIps('admin', 5);
		mocks.verifyPassword.mockClear();

		const r = await attemptLogin('10.9.9.9', 'admin', 'right');

		expect(r).toMatchObject({ ok: false, status: 429, retryAfter: 60 });
		expect(mocks.verifyPassword).not.toHaveBeenCalled();
	});

	it('locks unknown usernames the same way, so a 429 does not reveal they are unknown', async () => {
		await failFromManyIps('ghost', 5);

		expect(await attemptLogin('10.9.9.9', 'ghost', 'right')).toMatchObject({ status: 429, retryAfter: 60 });
	});

	it('doubles the lock per further failure and caps it at 15 minutes', async () => {
		await failFromManyIps('admin', 5);
		let lockMins = 1;
		for (const [i, mins] of [2, 4, 8, 15, 15].entries()) {
			vi.advanceTimersByTime(lockMins * MINUTE); // wait out the current lock
			expect(await attemptLogin(`10.2.0.${i}`, 'admin', 'wrong')).toMatchObject({ status: 401 });

			const r = await attemptLogin(`10.3.0.${i}`, 'admin', 'right');
			expect(r).toMatchObject({ status: 429, retryAfter: mins * 60 });
			lockMins = mins;
		}
	});

	it('lets the admin back in once the lock expires', async () => {
		await failFromManyIps('admin', 5);
		vi.advanceTimersByTime(MINUTE);

		expect(await attemptLogin('10.9.9.9', 'admin', 'right')).toMatchObject({ ok: true });
	});

	it('shows the wait in minutes for longer locks', async () => {
		await failFromManyIps('admin', 5);
		vi.advanceTimersByTime(MINUTE);
		await attemptLogin('10.2.0.1', 'admin', 'wrong');

		const r = await attemptLogin('10.3.0.1', 'admin', 'right');
		expect(r.ok === false && r.error).toBe('Too many login attempts. Please wait 2 minutes and try again.');
	});

	it('clears the failure count on a successful login', async () => {
		await failFromManyIps('admin', 4);
		expect(await attemptLogin('10.9.9.1', 'admin', 'right')).toMatchObject({ ok: true });

		await failFromManyIps('admin', 4);
		expect(await attemptLogin('10.9.9.2', 'admin', 'right')).toMatchObject({ ok: true });
	});

	it('forgets old failures after a quiet period', async () => {
		await failFromManyIps('admin', 4);
		vi.advanceTimersByTime(15 * MINUTE);

		await failFromManyIps('admin', 4);
		expect(await attemptLogin('10.9.9.9', 'admin', 'right')).toMatchObject({ ok: true });
	});
});
