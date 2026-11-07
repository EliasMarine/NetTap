import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import DnsResultPage from './+page.svelte';

// NET-192 PR 3: the daemon gives the resolver 6 s, then answers 200 with timed_out and no name

vi.mock('$app/stores', async () => {
	const { readable } = await import('svelte/store');
	return { page: readable({ url: new URL('http://localhost/lookup/dns/8.8.8.8'), params: { ip: '8.8.8.8' } }) };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

function answer(body: Record<string, unknown>): void {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) =>
			url.startsWith('/api/lookup/dns/')
				? { ok: true, status: 200, json: async () => ({ ip: '8.8.8.8', aliases: [], addresses: [], error: null, ...body }) }
				: { ok: false, status: 503, json: async () => ({}) },
		),
	);
}

describe('DNS lookup result', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('says the lookup timed out instead of "no record"', async () => {
		answer({ hostname: null, timed_out: true });
		render(DnsResultPage);
		expect(await screen.findByText('No reverse DNS name (lookup timed out)')).toBeInTheDocument();
		expect(screen.queryByText('No reverse DNS record')).not.toBeInTheDocument();
	});

	it('still says "no record" when the resolver answered without a name', async () => {
		answer({ hostname: null, timed_out: false });
		render(DnsResultPage);
		expect(await screen.findByText('No reverse DNS record')).toBeInTheDocument();
	});
});
