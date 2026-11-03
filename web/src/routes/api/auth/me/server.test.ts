import { describe, it, expect } from 'vitest';
import { GET } from './+server';

async function get(user?: { username: string; role: string }) {
	const res = await GET({ locals: { user } } as unknown as Parameters<typeof GET>[0]);
	return { status: res.status, headers: res.headers, body: await res.json() };
}

describe('GET /api/auth/me', () => {
	it('returns 401 with no identity headers when not logged in', async () => {
		const { status, headers, body } = await get();

		expect(status).toBe(401);
		expect(body).toEqual({ authenticated: false });
		expect(headers.get('X-NetTap-User')).toBeNull();
		expect(headers.get('X-NetTap-Role')).toBeNull();
	});

	it('sends the user and role as headers for nginx auth_request', async () => {
		const { status, headers, body } = await get({ username: 'alice', role: 'admin' });

		expect(status).toBe(200);
		expect(body).toEqual({ authenticated: true, user: { username: 'alice', role: 'admin' } });
		expect(headers.get('X-NetTap-User')).toBe('alice');
		expect(headers.get('X-NetTap-Role')).toBe('admin');
	});
});
