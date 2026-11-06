import { describe, it, expect, vi } from 'vitest';

const daemonFetch = vi.hoisted(() => vi.fn());
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch }));

import { GET } from './+server';

// NET-160 slice 2b-1: a smart alert's link narrows the list to its source → destination pair
describe('GET /api/alerts proxy', () => {
	it('forwards src and dst to the daemon, and leaves out empty ones', async () => {
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ alerts: [] }), { status: 200 }));
		const call = (query: string) => GET({ url: new URL(`http://x/api/alerts${query}`) } as unknown as Parameters<typeof GET>[0]);

		await call('?signature=ET+SCAN+x&src=192.168.1.20&dst=2001:db8::1');
		const sent = new URL(daemonFetch.mock.calls[0][0], 'http://daemon').searchParams;
		expect([sent.get('signature'), sent.get('src'), sent.get('dst')]).toEqual(['ET SCAN x', '192.168.1.20', '2001:db8::1']);

		await call('?src=&dst=');
		const empty = new URL(daemonFetch.mock.calls[1][0], 'http://daemon').searchParams;
		expect([empty.has('src'), empty.has('dst')]).toEqual([false, false]);
	});
});
