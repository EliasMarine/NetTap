import { describe, it, expect, vi } from 'vitest';

const daemonFetch = vi.hoisted(() => vi.fn());
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch }));

import { GET } from './+server';
import { GET as countGET } from './count/+server';

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

	// NET-160 slice 2b-2 (Codex #1): this explicit route forwards only what it names
	it('forwards suricata_category exactly as given, and leaves out an empty one', async () => {
		daemonFetch.mockReset();
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ alerts: [] }), { status: 200 }));
		const call = (query: string) => GET({ url: new URL(`http://x/api/alerts${query}`) } as unknown as Parameters<typeof GET>[0]);
		const sent = (i: number) => new URL(daemonFetch.mock.calls[i][0], 'http://daemon').searchParams;

		await call('?suricata_category=Misc+activity&src=192.168.1.20');
		expect([sent(0).get('suricata_category'), sent(0).get('src')]).toEqual(['Misc activity', '192.168.1.20']);

		await call(`?suricata_category=${encodeURIComponent('A/B & C')}`);
		expect(sent(1).get('suricata_category')).toBe('A/B & C');

		await call('?suricata_category=');
		expect(sent(2).has('suricata_category')).toBe(false);
	});

	// NET-191: only the literal `true` asks for the activity alerts
	it('forwards activity=true, and drops any other activity value', async () => {
		daemonFetch.mockReset();
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ alerts: [] }), { status: 200 }));
		const call = (query: string) => GET({ url: new URL(`http://x/api/alerts${query}`) } as unknown as Parameters<typeof GET>[0]);

		for (const query of ['?activity=true', '?activity=1', '?activity=TRUE', '?activity=true%26x%3D1', '?activity=']) await call(query);
		expect(daemonFetch.mock.calls.map(([path]) => path)).toEqual(['/api/alerts?activity=true', '/api/alerts', '/api/alerts', '/api/alerts', '/api/alerts']);
	});
});

describe('GET /api/alerts/count proxy', () => {
	it('forwards activity=true with the window, and drops any other activity value (NET-191)', async () => {
		daemonFetch.mockReset();
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ counts: {} }), { status: 200 }));
		const call = (query: string) => countGET({ url: new URL(`http://x/api/alerts/count${query}`) } as unknown as Parameters<typeof countGET>[0]);

		await call('?from=a&to=b&activity=true');
		await call('?from=a&to=b&activity=yes');
		await call('?from=a&to=b');
		expect(daemonFetch.mock.calls.map(([path]) => path)).toEqual([
			'/api/alerts/count?from=a&to=b&activity=true',
			'/api/alerts/count?from=a&to=b',
			'/api/alerts/count?from=a&to=b',
		]);
	});
});
