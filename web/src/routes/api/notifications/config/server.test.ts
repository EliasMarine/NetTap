import { describe, it, expect } from 'vitest';
import { POST } from './+server';

// F3: POST threw the body away and answered success, so the page said "saved successfully"
// when nothing was saved. Email and webhook come from the environment in this version.

async function post(body: unknown) {
	const request = new Request('http://localhost/api/notifications/config', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});
	const res = await POST({ request } as unknown as Parameters<typeof POST>[0]);
	return { status: res.status, body: await res.json() };
}

describe('POST /api/notifications/config', () => {
	it('says nothing was saved (501) instead of reporting success', async () => {
		const { status, body } = await post({ severityThreshold: 'high', webhook: { url: 'https://hooks.example.com/x' } });

		expect(status).toBe(501);
		expect(body).toEqual({
			error: "Not saved: email and webhook notifications can't be set from this page in this version.",
		});
		expect(body).not.toHaveProperty('success');
	});
});
