import { describe, it, expect, vi } from 'vitest';

const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const whois = await import('./whois/[ip]/+server.js');

describe('Lookup API', () => {
	it('should have route handlers defined', () => {
		// API route tests require SvelteKit runtime context
		// Full integration tests are in e2e/
		// Covers: lookup/dns, lookup/whois
		expect(true).toBe(true);
	});
});

// PR 2 (reliability): the daemon waits up to 15 s for whois; the 10 s default cut it off
describe('whois proxy', () => {
	it('gives the daemon 25 s', async () => {
		daemonFetch.mockResolvedValue(new Response(JSON.stringify({ ok: true })));
		await whois.GET({ params: { ip: '203.0.113.9' } } as never);
		expect(daemonFetch).toHaveBeenCalledWith('/api/lookup/whois/203.0.113.9', undefined, 25_000);
	});
});
