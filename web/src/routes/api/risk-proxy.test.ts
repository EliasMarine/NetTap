import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Risk score proxies (kept here because bracketed directory names trip some coverage globs).
 * Both dropped the query string, so from/to (and the list's limit) never reached the daemon.
 */
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const list = await import('./risk/scores/+server.js');
const single = await import('./risk/scores/[ip]/+server.js');

const RANGE = 'from=2026-11-01T00%3A00%3A00Z&to=2026-11-02T00%3A00%3A00Z';

describe('risk score proxies', () => {
	beforeEach(() => {
		daemonFetch.mockReset();
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ ok: true })));
	});

	it('the list forwards from, to and limit, and nothing else', async () => {
		const url = new URL(`https://nettap.local/api/risk/scores?${RANGE}&limit=50&other=x`);
		await list.GET({ url } as never);
		expect(daemonFetch).toHaveBeenCalledWith(`/api/risk/scores?${RANGE}&limit=50`);
	});

	it('the list still works with no query', async () => {
		await list.GET({ url: new URL('https://nettap.local/api/risk/scores') } as never);
		expect(daemonFetch).toHaveBeenCalledWith('/api/risk/scores');
	});

	it('a single device forwards from and to', async () => {
		const url = new URL(`https://nettap.local/api/risk/scores/192.168.1.1?${RANGE}`);
		await single.GET({ params: { ip: '192.168.1.1' }, url } as never);
		expect(daemonFetch).toHaveBeenCalledWith(`/api/risk/scores/192.168.1.1?${RANGE}`);
	});
});
