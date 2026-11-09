import { describe, it, expect } from 'vitest';
import { relayJSON } from './relay';

const answer = (body: string, status: number) => relayJSON(new Response(body, { status }));

describe('relayJSON', () => {
	it('passes JSON through with its status', async () => {
		const res = await answer('{"error":"Email: add at least one recipient"}', 400);
		expect(res.status).toBe(400);
		expect(await res.json()).toEqual({ error: 'Email: add at least one recipient' });
	});

	it('makes an unreadable 2xx a 502, so a page never reads { error } as its data', async () => {
		const res = await answer('<html>proxy page</html>', 200);
		expect(res.status).toBe(502);
		expect((await res.json()).error).toBe("NetTap's answer couldn't be read.");
	});

	it('keeps the status of an unreadable refusal', async () => {
		expect((await answer('', 503)).status).toBe(503);
	});
});
